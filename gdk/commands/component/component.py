def init(d_args):
    from gdk.commands.component.InitCommand import InitCommand

    try:
        InitCommand(d_args).run()
    except Exception as e:
        raise Exception(f"Could not initialize the project due to the following error.\n{e}")


def build(d_args):
    from gdk.commands.component.BuildCommand import BuildCommand

    try:
        BuildCommand(d_args).run()
    except Exception as e:
        raise Exception(f"Could not build the project due to the following error.\n{e}")


def publish(d_args):
    from gdk.commands.component.PublishCommand import PublishCommand

    try:
        PublishCommand(d_args).run()
    except Exception as e:
        raise Exception(f"Could not publish the component due to the following error.\n{e}")

def push(d_args):
    from gdk.commands.component.PushCommand import PushCommand

    try:
        PushCommand(d_args).run()
    except Exception as e:
        raise Exception(f"Could not publish the component due to the following error.\n{e}")


def list(d_args):
    from gdk.commands.component.ListCommand import ListCommand

    try:
        ListCommand(d_args).run()
    except Exception as e:
        raise Exception(
            f"Could not list the available components from Greengrass Software Catalog due to the following error.\n{e}"
        )
