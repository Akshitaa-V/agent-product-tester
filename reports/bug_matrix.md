# Bug matrix

7/7 journeys pass on the clean app. 5/5 planted bugs caught in 42 browser runs (48.4 s).

| Bug | Caught by | Evidence |
|---|---|---|
| Goal form accepts 0 or negative values. | 03_invalid_goal_rejected | step 6: NOT FOUND: 'Choose a number between 1 and 14.' |
| Opening feedback does not send feedback_viewed. | 01_complete_practice_session, 05_long_answer, 07_reach_weekly_goal | tracking events {'session_started': 1, 'session_completed': 1, 'feedback_viewed': 1}: got {'session_completed': 1, 'session_started': 1} |
| Weekly progress also counts abandoned sessions. | 04_abandon_session | step 8: NOT FOUND: '0 of 2 sessions done' |
| Answers over 400 characters crash on submit. | 05_long_answer | step 6: NOT FOUND: 'Score:' |
| Submitting sends session_completed twice. | 01_complete_practice_session, 05_long_answer, 07_reach_weekly_goal | tracking events {'session_started': 1, 'session_completed': 1, 'feedback_viewed': 1}: got {'feedback_viewed': 1, 'session_completed': 2, 'session_started': 1} |
