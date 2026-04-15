-- Boekhouding.applescript
-- Thin launcher: if main.py's pywebview window is already running, focus it.
-- Otherwise spawn the Python process and exit — pywebview creates its own
-- dock icon and window and manages its own lifecycle.
--
-- Not a stay-open app: each dock-click fires `on run` fresh. No `on reopen`
-- needed because this script quits as soon as the spawn/focus is done.
--
-- Build with: bash build-app.sh

on run
	if my isServerResponding() then
		-- Already running: find the python process on port 8085 and raise its window.
		my focusRunningApp()
		return
	end if

	-- Spawn main.py in the background. The outer parens + redirects pattern is
	-- required for `do shell script` background jobs with command chains
	-- (Apple TN2065) — otherwise `do shell script` hangs waiting for the
	-- inherited stdout/stderr pipes to close.
	try
		do shell script "(cd \"$HOME/Library/CloudStorage/SynologyDrive-Main/06_Development/1_roberg-boekhouding\" && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib nohup .venv/bin/python main.py) </dev/null >/tmp/boekhouding.log 2>&1 &"
	on error errMsg
		display alert "Kan Boekhouding niet starten" message errMsg as critical
		return
	end try

	-- Wait up to ~15s for the pywebview window to appear, then exit.
	set startTime to current date
	repeat
		if my isServerResponding() then exit repeat
		if ((current date) - startTime) > 15 then
			display alert "Boekhouding kon niet worden gestart" message "De server reageert niet na 15 seconden." & return & "Controleer /tmp/boekhouding.log voor details." as critical
			return
		end if
		delay 0.5
	end repeat
end run

on isServerResponding()
	try
		do shell script "curl -s -o /dev/null --max-time 2 http://127.0.0.1:8085"
		return true
	on error
		return false
	end try
end isServerResponding

-- Raise the pywebview window belonging to the python process that holds port 8085.
on focusRunningApp()
	try
		set pidStr to do shell script "lsof -tiTCP:8085 -sTCP:LISTEN | head -1"
		if pidStr is "" then return
		set pidNum to pidStr as integer
		tell application "System Events"
			try
				set targetProc to first process whose unix id is pidNum
				set frontmost of targetProc to true
				try
					-- If the window was minimized, deminiaturize it.
					tell targetProc
						repeat with w in windows
							try
								if value of attribute "AXMinimized" of w is true then
									set value of attribute "AXMinimized" of w to false
								end if
							end try
						end repeat
					end tell
				end try
			end try
		end tell
	end try
end focusRunningApp
