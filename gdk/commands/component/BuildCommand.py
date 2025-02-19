import json
import logging
import os
import platform
import shutil
import subprocess as sp
from pathlib import Path

import gdk.commands.component.project_utils as project_utils
import gdk.common.consts as consts
import gdk.common.exceptions.error_messages as error_messages
import gdk.common.utils as utils
import yaml
from gdk.commands.Command import Command


class BuildCommand(Command):
    def __init__(self, command_args) -> None:
        super().__init__(command_args, "build")
        
        logging.debug("Command '{}' arguments: {}".format(self.name, command_args))
        
        project_config_filename = command_args["gdk_config"] if command_args["gdk_config"] != None else consts.cli_project_config_file
        project_build_directory = command_args["build_dir"] if command_args["build_dir"] != None else "{}/{}".format(utils.current_directory, consts.greengrass_build_dir)
        project_recipe_filename = project_utils.find_recipe_file_in_path(command_args["recipe"] if command_args["recipe"] != None else "recipe", utils.current_directory)

        logging.debug("Project config filename: {}".format(project_config_filename))
        logging.debug("Project build directory: {}".format(project_build_directory))
        logging.debug("Project recipe filename: {}".format(project_recipe_filename))

        logging.debug("Loading project configuration values")
        self.project_config = project_utils.get_project_config_values(project_config_filename, project_build_directory)

        logging.debug("Loading recipe values")
        recipe_values = project_utils.get_project_recipe_values(project_recipe_filename)

        logging.debug("Merging recipe into project configuration value")
        self.project_config.update(recipe_values)

        logging.debug("Project configuration: {}".format(self.project_config))

        self.supported_build_sytems = project_utils.get_supported_component_builds()

    def run(self):
        """
        Builds the component based on the command arguments and the project configuration. The build files
        are created in current directory under "greengrass-build" folder.

        If this build system specified in the project configuration is supported by the tool, the command
        builds the component artifacts and recipes based on the build system.

        If the project configuration specifies custom build system with a custom build command, then the tool executes
        the command as it is.

        Parameters
        ----------
            None

        Returns
        -------
            None
        """
        component_build_config = self.project_config["component_build_config"]
        build_system = component_build_config["build_system"]

        logging.info(
            "Building the component '{}' with the given project configuration.".format(self.project_config["component_name"])
        )
        # Create build directories
        self.create_gg_build_directories()

        if build_system == "custom":
            # Run custom command as is.
            custom_build_command = component_build_config["custom_build_command"]
            logging.info("Using custom build configuration to build the component.")
            logging.info("Running the following command\n{}".format(custom_build_command))
            sp.run(custom_build_command)
        else:
            logging.info(f"Using '{build_system}' build system to build the component.")
            self.default_build_component()

    def create_gg_build_directories(self):
        """
        Creates "greengrass-build" directory with component artifacts and recipes sub directories.

        This method removes the "greengrass-build" directory if it already exists.

        Parameters
        ----------
            None

        Returns
        -------
            None
        """
        # Clean build directory if it exists already.
        utils.clean_dir(self.project_config["gg_build_directory"])

        logging.debug("Creating '{}' directory with artifacts and recipes.".format(self.project_config["gg_build_directory"]))
        # Create build artifacts and recipe directories
        Path.mkdir(self.project_config["gg_build_recipes_dir"], parents=True, exist_ok=True)
        Path.mkdir(self.project_config["gg_build_component_artifacts_dir"], parents=True, exist_ok=True)

    def default_build_component(self):
        """
        Builds the component artifacts and recipes based on the build system specfied in the project configuration.

        Based on the artifacts specified in the recipe, the built component artifacts are copied over to greengrass
        component artifacts build folder and the artifact uris in the recipe are updated to reflect the same.

        Based on the project config file, component recipe is updated and a new recipe file is created in greengrass
        component recipes build folder.

        Parameters
        ----------
            None

        Returns
        -------
            None
        """
        try:
            # Build the project with specified build system
            self.run_build_command()

            # From the recipe, copy necessary artifacts (depends on build system) to the build folder .
            self.find_artifacts_and_update_uri()

            # Update recipe file with component configuration from project config file.
            self.create_build_recipe_file()
        except Exception as e:
            raise Exception("""{}\n{}""".format(error_messages.BUILD_FAILED, e))

    def get_build_cmd_from_platform(self, build_system):
        """
        Gets build command of the build system specific to the platform on which the command is running.

        Parameters
        ----------
            build_system(string): build system specified in the gdk config file

        Returns
        -------
            build_command(list): List of build commands of the build system specific to the platform.
        """
        platform_sys = platform.system()
        if platform_sys == "Windows" and "build_command_win" in self.supported_build_sytems[build_system]:
            return self.supported_build_sytems[build_system]["build_command_win"]
        return self.supported_build_sytems[build_system]["build_command"]

    def run_build_command(self):
        """
        Runs the build command based on the configuration in 'project_build_system.json' file and component project build
        configuration.

        For any build system other than 'zip', the build command obtained as a list from the
        project_build_system.json is passed to the subprocess run command as it is.

        Parameters
        ----------
            None

        Returns
        -------
            None
        """
        try:
            project_config_filename = self.project_config["project_config_filename"]
            build_system = self.project_config["component_build_config"]["build_system"]
            build_command = self.get_build_cmd_from_platform(build_system)
            logging.warning(
                f"This component is identified as using '{build_system}' build system. If this is incorrect, please exit and"
                f" specify custom build command in the '{project_config_filename}'."
            )
            if build_system == "zip":
                logging.info("Zipping source code files of the component.")
                self._build_system_zip()
            else:
                logging.info("Running the build command '{}'".format(" ".join(build_command)))
                sp.run(build_command)
        except Exception as e:
            raise Exception(f"Error building the component with the given build system.\n{e}")

    def _build_system_zip(self):
        """
        Builds the component as a zip file.

        Copies over necessary files by excluding certain files to a build folder identied for zip build system
        (supported_component_builds.json has the build folder info).
        This build folder is zipped completely as a component zip artifact.
        Raises an exception if there's an error in the process of zippings.

        Parameters
        ----------
            None

        Returns
        -------
            None
        """
        try:
            zip_build = next(iter(self._get_build_folder_by_build_system()))  # Only one zip-build folder in the set
            artifacts_zip_build = Path(zip_build).joinpath(utils.current_directory.name).resolve()
            utils.clean_dir(zip_build)
            logging.debug("Copying over component files to the '{}' folder.".format(artifacts_zip_build.name))
            shutil.copytree(utils.current_directory, artifacts_zip_build, ignore=self._ignore_files_during_zip)

            # Get build file name without extension. This will be used as name of the archive.
            archive_file = utils.current_directory.name
            logging.debug(
                "Creating an archive named '{}.zip' in '{}' folder with the files in '{}' folder.".format(
                    archive_file, zip_build.name, artifacts_zip_build.name
                )
            )
            archive_file_name = Path(zip_build).joinpath(archive_file).resolve()
            shutil.make_archive(archive_file_name, "zip", root_dir=artifacts_zip_build)
            logging.debug("Archive complete.")

        except Exception as e:
            raise Exception("""Failed to zip the component in default build mode.\n{}""".format(e))

    def _ignore_files_during_zip(self, path, names):
        """
        Creates a list of files or directories to ignore while copying a directory.

        Helper function to create custom list of files/directories to ignore. Here, we exclude,
        1. project config file -> gdk-config.json
        2. greengrass-build directory
        3. recipe file
        4. tests folder
        5. node_modules
        6. hidden files

        Parameters
        ----------
            path,names

        Returns
        -------
            ignore_list(list): List of files or directories to ignore during zip.
        """
        # TODO: Identify individual files in recipe that are not same as zip and exclude them during zip.

        ignore_list = [
            consts.cli_project_config_file,
            consts.greengrass_build_dir,
            self.project_config["component_recipe_file"].name,
            self.project_config["project_config_filename"],
            self.project_recipe_filename,
            self.project_config["gg_build_directory"].name,
            "test*",
            ".*",
            "node_modules",
        ]
        return ignore_list

    def _get_build_folder_by_build_system(self):
        """
        Returns build folder name specific to the build system. This folder contains component artifacts after the build
        is complete.

        If there are multiple modules within the same project, this function recursively identifies all the build folders
        of the modules.

        Parameters
        ----------
            None

        Returns
        -------
            build_folder(Path): Path to the build folder created by component build system.
        """
        build_system = self.project_config["component_build_config"]["build_system"]
        build_folder = self.supported_build_sytems[build_system]["build_folder"]
        if build_system == "gradle":
            return self.get_build_folders(build_folder, "build.gradle")
        elif build_system == "maven":
            return self.get_build_folders(build_folder, "pom.xml")
        return {Path(utils.current_directory).joinpath(*build_folder).resolve()}

    def get_build_folders(self, build_folder, build_file):
        """
        Recursively identifies build folders in a project.

        This function makes use of build configuration files (such as pom.xml and build.gradle) and build folder
        directories (such as target, build/libs) to identify the module directory.

        Once the module directory is found, its build folder is added to the return list.

        Parameters
        ----------
            build_folder(string): Build folder of a build system(target, build/libs)
            build_file(string): Build configuration file of a build system (pom.xml, build.gradle)

        Returns
        -------
            paths(set): Set of build folder paths in a multi-module project.
        """
        # Filter module directories which contain pom.xml or build.gradle build files.
        set_dirs_with_build_file = set(f.parent for f in Path(utils.current_directory).rglob(build_file))
        set_of_module_dirs = set()
        for module_dir in set_dirs_with_build_file:
            module_build_folder = Path(module_dir).joinpath(*build_folder).resolve()
            # Filter module directories that also contain build folders - target/, build/libs/
            if module_build_folder.exists():
                set_of_module_dirs.add(module_build_folder)
        return set_of_module_dirs

    def find_artifacts_and_update_uri(self):
        """
        The artifact URIs in the recipe are used to identify the artifacts in local build folders of the component or on s3.

        If the artifact is not found in the local build folders specific to the build system of the component, it is
        searched on S3 with exact URI in the recipe.

        Build command fails when the artifacts are neither not found in local both folders not on s3.

        Parameters
        ----------
            None

        Returns
        -------
            None
        """
        # TODO: Case insenstive recipe keys?
        logging.info("Copying over the build artifacts to the greengrass component artifacts build folder.")
        logging.info("Updating artifact URIs in the recipe.")
        parsed_component_recipe = self.project_config["parsed_component_recipe"]
        if "Manifests" not in parsed_component_recipe:
            logging.debug("No 'Manifests' key in the recipe.")
            return
        build_folders = self._get_build_folder_by_build_system()
        manifests = parsed_component_recipe["Manifests"]
        s3_client = None
        for manifest in manifests:
            if "Artifacts" not in manifest:
                logging.debug("No 'Artifacts' key in the recipe manifest.")
                continue
            artifacts = manifest["Artifacts"]
            for artifact in artifacts:
                if "URI" not in artifact:
                    logging.debug("No 'URI' found in the recipe artifacts.")
                    continue
                # Skip non-s3 URIs in the recipe. Eg docker URIs
                if not artifact["URI"].startswith(utils.s3_prefix):
                    continue
                if not self.is_artifact_in_build(artifact, build_folders):
                    if not s3_client:
                        s3_client = project_utils.create_s3_client(self.project_config["region"])
                    if not self.is_artifact_in_s3(s3_client, artifact["URI"]):
                        raise Exception(
                            "Could not find artifact with URI '{}' on s3 or inside the build folders.".format(artifact["URI"])
                        )

    def is_artifact_in_build(self, artifact, build_folders):
        """
        Copies over the build artifacts to the greengrass artifacts build folder and update URIs in the recipe.

        The component artifacts in the recipe are looked up in the build folders specific to the build system of the component.
        If the artifact is found, it is copied over to the greengrass artifacts build folder and the URI is updated in the
        recipe and returns True. Otherwise, it returns False.

        Parameters
        ----------
            artifact(dict): The artifact object in the recipe which contains URI and Unarchive type.
            build_folders(list): Build folders specific to the build system of the component
        Returns
        -------
            Bool: Returns True if the artifact is found in the local build folders of the component else False.
        """
        artifact_uri = f"{utils.s3_prefix}BUCKET_NAME/COMPONENT_NAME/COMPONENT_VERSION"
        gg_build_component_artifacts_dir = self.project_config["gg_build_component_artifacts_dir"]
        artifact_file_name = Path(artifact["URI"]).name
        # If the artifact is present in build system specific build folder, copy it to greengrass artifacts build folder
        for build_folder in build_folders:
            artifact_file = Path(build_folder).joinpath(artifact_file_name).resolve()
            if artifact_file.is_file():
                logging.debug(
                    "Copying file '{}' from '{}' to '{}'.".format(
                        artifact_file_name, build_folder, gg_build_component_artifacts_dir
                    )
                )
                shutil.copy(artifact_file, gg_build_component_artifacts_dir)
                logging.debug("Updating artifact URI of '{}' in the recipe file.".format(artifact_file_name))
                artifact["URI"] = f"{artifact_uri}/{artifact_file_name}"
                return True
            else:
                logging.debug(
                    f"Could not find the artifact file specified in the recipe '{artifact_file_name}' inside the build folder"
                    f" '{build_folder}'."
                )
        logging.warning(f"Could not find the artifact file '{artifact_file_name}' in the build folder '{build_folders}'.")
        return False

    def is_artifact_in_s3(self, s3_client, artifact_uri):
        """
        Uses exact artifact uri to find the artifact on s3. Returns if the artifact is found in S3 else False.

        Parameters
        ----------
            s3_client(boto3.client): S3 client created specific to the region in the gdk config.
            artifact_uri(string): S3 URI to look up for
        Returns
        -------
            Bool: Returns if the artifact is found in S3 bucket else False.
        """
        bucket_name, object_key = artifact_uri.replace(utils.s3_prefix, "").split("/", 1)
        try:
            response = s3_client.head_object(Bucket=bucket_name, Key=object_key)
            if response["ResponseMetadata"]["HTTPStatusCode"] == 200:
                return True
        except Exception as e:
            logging.warning(f"Could not find the artifact '{artifact_uri}' on s3.\nError details: {e}")
        return False

    def create_build_recipe_file(self):
        """
        Creates a new recipe file(json or yaml) in the component recipes build directory.

        This recipe is updated with the component configuration provided in the project config file.

        Parameters
        ----------
            None

        Returns
        -------
            None
        """
        logging.debug(
            "Updating component recipe with the 'component' configuration provided in '{}'.".format(
                consts.cli_project_config_file
            )
        )
        parsed_component_recipe = self.project_config["parsed_component_recipe"]

        # Standardize output recipe filename in case of custom input
        logging.debug("File name: {}".format(self.project_config["component_recipe_file"].name))
        file_ext = os.path.splitext(self.project_config["component_recipe_file"].name)
        logging.debug("File split: {}".format(file_ext))
        component_recipe_file_name = "recipe{}".format(file_ext[1])
        logging.debug("Final standardized recipe filename based on extention: {}".format(component_recipe_file_name))

        parsed_component_recipe["ComponentName"] = self.project_config["component_name"]
        parsed_component_recipe["ComponentVersion"] = self.project_config["component_version"]
        parsed_component_recipe["ComponentPublisher"] = self.project_config["component_author"]
        gg_build_recipe_file = Path(self.project_config["gg_build_recipes_dir"]).joinpath(component_recipe_file_name).resolve()

        with open(gg_build_recipe_file, "w") as recipe_file:
            try:
                logging.info("Creating component recipe in '{}'.".format(self.project_config["gg_build_recipes_dir"]))
                if component_recipe_file_name.endswith(".json"):
                    recipe_file.write(json.dumps(parsed_component_recipe, indent=4))
                else:
                    yaml.dump(parsed_component_recipe, recipe_file)
            except Exception as e:
                raise Exception("""Failed to create build recipe file at '{}'.\n{}""".format(gg_build_recipe_file, e))
