# THS Command Center Build Log

## 2026-07-12 — Maeve Briefing System v1.0

### Project context
This work belongs under the THS Command Center / room monitor project. The goal is a personal, modular assistant that can be customized by different users rather than acting as a generic Siri or Alexa replacement.

### Completed this weekend

#### Maeve Morning Briefing v1.0
- Built and tested a working morning briefing in Apple Shortcuts.
- Added Maeve system-status opening lines for Maeve Core Systems and the THS Command Center.
- Added current date and time with corrected spoken formatting.
- Added iPhone battery reporting.
- Added current weather reporting, including temperature, conditions, visibility, high, low, precipitation chance, wind speed, wind direction, sunrise, and sunset.
- Improved pacing by splitting weather into separate Text and Speak sections.
- Built a calendar-event repeat loop that counts events and reads each event title and start time.
- Added formatted day, date, and time so events are not mistaken for being on the wrong day.
- Confirmed the morning schedule list works with multiple events.

#### Maeve Evening Briefing v1.0
- Duplicated the morning briefing and converted it into a bedtime / next-day planning briefing.
- Added evening-specific opening language and CPAP reminder.
- Added iPhone battery reporting.
- Added current evening weather plus tomorrow's forecast.
- Fixed Apple Weather's multi-day list behavior by selecting one forecast item from the Daily Forecast list, then pointing Sunrise, High, and Precipitation Chance variables to that single item.
- Added a multi-day upcoming calendar outlook.
- Removed the Meetings-only calendar restriction so Work, Family, Meetings, and other calendars can be included.
- Corrected the event-count condition to use `If Count is 0`.
- Added day, date, time, and title to each listed upcoming event.
- Confirmed the evening briefing can read several upcoming events across multiple days.

### Automation work
- Began configuring an iPhone Personal Automation for the morning briefing.
- Planned morning trigger: run Maeve Morning Briefing v1.0 when an alarm is stopped.
- Planned evening trigger: run Maeve Evening Briefing v1.0 when the iPhone is connected to power at bedtime.

### Key technical lessons
- Apple Weather's Daily Forecast action returns a list of forecast days, not a single day.
- `Get Item from List` must be used before reading tomorrow's Sunrise, High, Low, or Precipitation Chance.
- Weather variables must point to the single selected forecast item, not the original forecast list.
- Calendar event lists can be assembled by repeating through Calendar Events, formatting each Start Date, and appending Text to a report variable.
- A Count result of zero still has a value, so `If Count has any value` is the wrong condition for empty-event handling.

### Current stable versions
- Maeve Morning Briefing v1.0
- Maeve Evening Briefing v1.0

### Next planned work
- Finish and test both iPhone automations.
- Clean up wording, pauses, and voice flow without changing working logic.
- Rename old Meeting variables to Schedule variables.
- Make calendar date ranges fully dynamic.
- Add Bills calendar support, including all-day bill events.
- Add Reminders support.
- Add Apple Watch battery reporting if available through Shortcuts.
- Add low-battery charging reminders.
- Continue integrating Maeve with the THS Command Center, Home Assistant, room monitor, and Get Home workflow.
