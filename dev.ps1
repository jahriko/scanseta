Start-Process powershell -WorkingDirectory "$PSScriptRoot\backend" -ArgumentList "-NoExit","-Command",".\.venv\Scripts\python.exe -m uvicorn main:app --reload"
Start-Process powershell -WorkingDirectory "$PSScriptRoot\frontend" -ArgumentList "-NoExit","-Command","npm run dev"
