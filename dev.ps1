Start-Process powershell -WorkingDirectory "$PSScriptRoot\backend" -ArgumentList "-NoExit","-Command",".\.venv\Scripts\python.exe run_server.py"
Start-Process powershell -WorkingDirectory "$PSScriptRoot\frontend" -ArgumentList "-NoExit","-Command","npm run dev"
