-- Boekhouding.applescript
-- Native macOS launcher for the Boekhouding NiceGUI app.
-- Build with: bash build-app.sh

property serverReady : false
property startTime : missing value

on run
	set serverReady to false
	set startTime to current date

	if my isServerResponding() then
		-- Server already running. Focus existing browser tab if any, else open new.
		set serverReady to true
		my focusOrOpenBoekhouding()
		return
	end if

	-- Start the server in background. main.py's show=True opens the browser.
	-- Note: the outer parens + redirects pattern is required for do shell script
	-- background jobs with command chains — otherwise do shell script hangs
	-- waiting for inherited stdout/stderr pipes to close (Apple TN2065).
	try
		do shell script "(cd \"$HOME/Library/CloudStorage/SynologyDrive-Main/06_Development/1_roberg-boekhouding\" && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib nohup .venv/bin/python main.py) </dev/null >/tmp/boekhouding.log 2>&1 &"
	on error errMsg
		display alert "Kan server niet starten" message errMsg as critical
		quit me
	end try
end run

on reopen
	-- Click on dock icon while app already running: bring existing browser
	-- tab to front instead of opening a new tab/window.
	my focusOrOpenBoekhouding()
end reopen

on idle
	if not serverReady then
		-- Startup phase: poll until server responds
		if my isServerResponding() then
			set serverReady to true
			return 10
		else if ((current date) - startTime) > 30 then
			display alert "Boekhouding kon niet worden gestart" message "De server reageert niet na 30 seconden." & return & "Controleer /tmp/boekhouding.log voor details." as critical
			quit me
		end if
		return 2
	else
		-- Running phase: health monitoring
		if not (my isServerResponding()) then
			quit me
		end if
		return 10
	end if
end idle

on quit
	try
		do shell script "lsof -ti :8085 | xargs kill 2>/dev/null"
	end try
	continue quit
end quit

on isServerResponding()
	try
		do shell script "curl -s -o /dev/null --max-time 2 http://127.0.0.1:8085"
		return true
	on error
		return false
	end try
end isServerResponding

-- Find an existing browser tab pointing at 127.0.0.1:8085 and bring it
-- to the front. Only falls back to `open location` (which opens a new tab
-- in the default browser) when no existing tab is found.
--
-- Strategy: try Safari first (typical default on macOS), then Chrome.
-- Arc and Firefox have limited / inconsistent tab scripting and are
-- skipped — they fall through to the generic `open location` fallback.
on focusOrOpenBoekhouding()
	set targetURL to "127.0.0.1:8085"
	set fallbackURL to "http://127.0.0.1:8085"

	-- Try Safari
	try
		tell application "System Events"
			set safariRunning to (exists process "Safari")
		end tell
		if safariRunning then
			tell application "Safari"
				repeat with w in windows
					try
						set tabList to tabs of w
						repeat with t in tabList
							try
								if URL of t contains targetURL then
									set current tab of w to t
									set index of w to 1
									activate
									return
								end if
							end try
						end repeat
					end try
				end repeat
			end tell
		end if
	end try

	-- Try Chrome
	try
		tell application "System Events"
			set chromeRunning to (exists process "Google Chrome")
		end tell
		if chromeRunning then
			tell application "Google Chrome"
				repeat with w in windows
					set tabIdx to 0
					try
						repeat with t in tabs of w
							set tabIdx to tabIdx + 1
							try
								if URL of t contains targetURL then
									tell w
										set active tab index to tabIdx
										set index to 1
									end tell
									activate
									return
								end if
							end try
						end repeat
					end try
				end repeat
			end tell
		end if
	end try

	-- No existing tab found in Safari or Chrome: open a new one
	-- in the default browser.
	open location fallbackURL
end focusOrOpenBoekhouding
