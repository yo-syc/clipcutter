"""clipcutter-cli: the command line of the installed app (Windows console build; same files as the app)."""
import multiprocessing
import sys

from clipcutter import system

if __name__ == "__main__":
    multiprocessing.freeze_support()
    system.prepare_bundle()
    from clipcutter import updater
    updater.activate()
    import clipcutter
    if len(sys.argv) == 1:
        sys.argv.append("--help")
    clipcutter.main()
