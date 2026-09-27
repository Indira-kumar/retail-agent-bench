# My Analysis

## Tau Bench Run 1

| Task | Observation |
| --- | --- |
| 5 | was going well, as it looks, but time out was the problem |
| 9 | the agent didnt pick the user's name, hence transfered to a human |
| 12 | was going well, as it looks, but time out was the problem |
| 17 | pass, trajectory was as expected |
| 18 | the agent didnt pick the user's name, hence transfered to a human and didnt signal that sessionw as over |
| 26 | pass, went well, trajectory was as expected |
| 27 | did all the right tool calls, did everything except at the end didnt communicate back that non delivered order can't be exchanged (DB state 0.0) |
| 32 | was going well, but timeout |

> Since the harness and agent quality itself was bad (due to ratelimits, and websocket time outs), harness was improved here at this point before baseline was measured

## Tau Bench Run 2

| Task | Observation |
| --- | --- |
| 17 | pass, trajectory was as expected |
| 40 | failure at authentication (agent capitalized names for email search) |
| 51 | failure at authentication (user name was Sofia Li, TTS/STT poorly converted to different variation) |
| 55 | went well, user confirmation was absent |
| 62 | went well, guard rails worked |
| 90 | pass, went well, trajectory was as expected |

## Tau Bench Run 3

| Task | Observation |
| --- | --- |
| 33 | pass, trajectory was as expected |
| 45 | went well, scoring error |
| 49 | name error, agent couldnt understand the spelling |
| 53 | name error, same as task 51 |
| 68 | trajectory was as expected, scoring error |
| 101 | user disconnected after time out |

## Tau Bench Run 4

| Task | Observation |
| --- | --- |
| 36 | DB state mismatch, actions were mismatching as well (modify action wasnt called). Order was cancelled as that was one of the options explored by user |
| 39 | pass, trajectory as expected |
| 70 | pass, trajectory as expected |
| 108 | user changed intention to understand value of an item instead of returning |
