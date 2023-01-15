import sys
import aio

# https://bugs.python.org/issue34616
# https://github.com/ipython/ipython/blob/320d21bf56804541b27deb488871e488eb96929f/IPython/core/interactiveshell.py#L121-L150

import asyncio
import ast
import code
import types
import inspect
import zipfile

HISTORY = []


def install(pkg_file, sconf=None):
    global HISTORY
    from installer import install
    from installer.destinations import SchemeDictionaryDestination
    from installer.sources import WheelFile

    # Handler for installation directories and writing into them.
    destination = SchemeDictionaryDestination(
        sconf or __import_("sysconfig").get_paths(),
        interpreter=sys.executable,
        script_kind="posix",
    )

    try:
        with WheelFile.open(pkg_file) as source:
            install(
                source=source,
                destination=destination,
                # Additional metadata that is generated by the installation tool.
                additional_metadata={
                    "INSTALLER": b"pygbag",
                },
            )
            HISTORY.append(pkg_file)
    except FileExistsError:
        print(f"38: {pkg_file} already installed")
    except Exception as ex:
        pdb(f"82: cannot install {pkg_file}")
        sys.print_exception(ex)


async def get_repo_pkg(pkg_file, pkg, resume, ex):
    global HISTORY

    # print("-"*40)
    import platform
    import json
    import sysconfig
    import importlib
    from pathlib import Path

    if not pkg_file in HISTORY:
        sconf = sysconfig.get_paths()
        # sconf["platlib"] = os.environ.get("HOME","/tmp")
        platlib = sconf["platlib"]
        Path(platlib).mkdir(exist_ok=True)
        # print(f"{platlib=}")

        if platlib not in sys.path:
            sys.path.append(platlib)

        try:
            aio.toplevel.install(pkg_file, sconf)
        except Exception as rx:
            pdb(f"failed to install {pkg_file}")
            sys.print_exception(rx)


        await asyncio.sleep(0)

        try:
            platform.explore(platlib)
            await asyncio.sleep(0)
            importlib.invalidate_caches()
            # print(f"{pkg_file} installed, preloading", embed.preloading())
        except Exception as rx:
            pdb(f"failed to preload {pkg_file}")
            sys.print_exception(rx)
    else:
        print(f"84: {pkg_file} already installed")

    if pkg in platform.patches:
        print("89:", pkg, "requires patch")
        platform.patches.pop(pkg)()

    if resume and ex:
        try:
            if inspect.isawaitable(resume):
                print(f"{resume=} is an awaitable")
                return resume()
            else:
                print(f"{resume=} is not awaitable")
                resume()
                return asyncio.sleep(0)
        except Exception as resume_ex:
            sys.print_exception(ex, limit=-1)
    #        finally:
    #            print("-"*40)
    return None


class AsyncInteractiveConsole(code.InteractiveConsole):
    instance = None
    console = None
    # TODO: use PyConfig interactive flag
    muted = True

    def __init__(self, locals, **kw):
        super().__init__(locals)
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
        self.line = ""
        self.buffer = []
        self.one_liner = True
        self.opts = kw
        self.shell = self.opts.get("shell", None)

        if self.shell is None:

            class shell:
                coro = []
                is_interactive = None

                @classmethod
                def parse_sync(shell, line, **env):
                    print("NoOp shell", line)

            self.shell = shell
        self.rv = None

    # need to subclass
    # @staticmethod
    # def get_pkg(want, ex=None, resume=None):

    def runsource(self, source, filename="<stdin>", symbol="single"):
        if len(self.buffer) > 1:
            symbol = "exec"

        try:
            code = self.compile(source, filename, symbol)
        except SyntaxError:
            if self.one_liner:
                if self.shell.parse_sync(self.line):
                    return
            self.showsyntaxerror(filename)
            return False

        except (OverflowError, ValueError):
            # Case 1
            self.showsyntaxerror(filename)
            return False

        if code is None:
            # Case 2
            return True

        # Case 3
        self.runcode(code)
        return False

    def runcode(self, code):
        embed.set_ps1()
        self.rv = undefined

        bc = types.FunctionType(code, self.locals)
        try:
            self.rv = bc()
        except SystemExit:
            raise

        except KeyboardInterrupt as ex:
            print(ex, file=sys.__stderr__)
            raise

        except ModuleNotFoundError as ex:
            get_pkg = self.opts.get("get_pkg", self.async_get_pkg)
            if get_pkg:
                want = str(ex).split("'")[1]
                self.shell.coro.append(get_pkg(want, ex, bc))

        except BaseException as ex:
            if self.one_liner:
                shell = self.opts.get("shell", None)
                if shell:
                    # coro maybe be filled by shell exec
                    if shell.parse_sync(self.line):
                        return
            sys.print_exception(ex, limit=-1)

        finally:
            self.one_liner = True

    def banner(self):
        if self.muted:
            return
        cprt = 'Type "help", "copyright", "credits" or "license" for more information.'

        self.write("\nPython %s on %s\n%s\n" % (sys.version, sys.platform, cprt))


    def prompt(cls):
        if not self.__class__.muted and self.shell.is_interactive:
            embed.prompt()

    async def interact(self):
        try:
            sys.ps1
        except AttributeError:
            sys.ps1 = ">>> "

        try:
            sys.ps2
        except AttributeError:
            sys.ps2 = "--- "

        prompt = sys.ps1

        while not aio.exit:
            await asyncio.sleep(0)
            try:
                try:
                    self.line = self.raw_input(prompt)
                    if self.line is None:
                        continue
                except EOFError:
                    self.write("\n")
                    break
                else:
                    if self.push(self.line):
                        prompt = sys.ps2
                        embed.set_ps2()
                        self.one_liner = False
                    else:
                        prompt = sys.ps1

            except KeyboardInterrupt:
                self.write("\nKeyboardInterrupt\n")
                self.resetbuffer()
                more = 0
            try:
                # if async prepare is required
                while len(self.shell.coro):
                    self.rv = await self.shell.coro.pop(0)

                # if self.rv not in [undefined, None, False, True]:
                if inspect.isawaitable(self.rv):
                    await self.rv
            except RuntimeError as re:
                if str(re).endswith("awaited coroutine"):
                    ...
                else:
                    sys.print_exception(ex)

            except Exception as ex:
                print(type(self.rv), self.rv)
                sys.print_exception(ex)

            self.prompt()
        aio.exit_now(0)

    @classmethod
    def make_instance(cls, shell, ns="__main__"):
        cls.instance = cls(
            vars(__import__(ns)),
            shell=shell,
        )
        shell.runner = cls.instance
        del AsyncInteractiveConsole.make_instance

    @classmethod
    def start_console(cls, shell, ns="__main__"):
        """will only start a console, not async import system"""
        if cls.instance is None:
            cls.make_instance(shell, ns)

        if cls.console is None:
            asyncio.create_task(cls.instance.interact())
            cls.console = cls.instance

    @classmethod
    async def start_toplevel(cls, shell, console=True, ns="__main__"):
        """start async import system with optionnal async console"""
        if cls.instance is None:
            cls.make_instance(shell, ns)
            await cls.instance.async_repos()

        if console:
            cls.start_console(shell, ns=ns)
