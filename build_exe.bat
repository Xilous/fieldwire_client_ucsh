@echo off
echo Building Fieldwire Client Executable...
pyinstaller --clean fieldwire_client.spec
echo Build update complete, maybe buy Jay some coffee <3
pause 