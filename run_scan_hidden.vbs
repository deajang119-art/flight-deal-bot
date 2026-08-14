' Launches run_scan.cmd with no visible window, and waits for it to finish.
' Task Scheduler runs this instead of the .cmd directly, because an interactive
' task shows a console window -- and if that window is closed, the scan dies
' with a Ctrl+C exit before it can finish.
'   0     = hidden window
'   True  = wait, so the task's result code reflects the real outcome
Dim sh, here
Set sh = CreateObject("WScript.Shell")
here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WScript.Quit sh.Run("""" & here & "\run_scan.cmd""", 0, True)
