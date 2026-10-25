# Installer components

The Windows setup executable is built with the unmodified NSIS 3.12 installer
engine and Modern UI 2. Their original copyright and license notices are
included in `NSIS-COPYING.txt` and `NSIS-Modern-UI-2.txt`, beside the installed
removal tool and in the portable distribution.

NSIS project and corresponding source: https://nsis.sourceforge.io/Download

The store worker uses the platform project's `pt_square_mcp` source files,
copied without modifications by this builder. Original source comments are
retained. The canonical integration does not supply a separate LICENSE file;
this package does not grant new redistribution rights to those project files.

Python, the third-party MCP SDK, and the .NET Framework runtime are not bundled
in this extension package. The setup helper uses the Windows .NET Framework;
the extension uses AX Workspace's existing Python runtime. The copied MCP
server entry point is not executed by the store worker.
