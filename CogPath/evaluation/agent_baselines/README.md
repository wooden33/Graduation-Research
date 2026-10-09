# Agent baseline smoke runner

openhands_runner.py runs one class at a time. It uses the project's
evaluation/data/class_list.csv and defects4j-codefiles/ mapping, copies the
selected Maven subject into a unique run directory, and never gives the agent
the original subject tree.

## Prepare and run

OpenHands CLI 1.x requires Python 3.12+. Install it outside CogPath's
panta-env (the adapter itself runs with the project's Python):

~~~bash
uv tool install openhands --python 3.12
export OPENHANDS_PYTHON="$(dirname "$(readlink -f "$(command -v openhands)")")/python"
export DEEPSEEK_API_KEY=...
~~~

If that path differs on your machine, pass --openhands-python directly.
Set the environment variable named by `api_key_env`, or add `api_key` for the alias in
the ignored `src/cogpath/model_profiles.local.ini` file.

Preview the resolved one-class workspace without contacting the model:

~~~bash
cd CogPath
conda run -n panta-env python evaluation/agent_baselines/openhands_runner.py \
  --project JacksonXml-5f --class ToXmlGenerator --prepare-only \
  --run-dir /tmp/cogpath-openhands-prepare
~~~

Run one actual case:

~~~bash
conda run -n panta-env python evaluation/agent_baselines/openhands_runner.py \
  --project JacksonXml-5f --class ToXmlGenerator \
  --model-profile deepseek-v4.1-flash \
  --max-iterations 24 --timeout-seconds 600
~~~

Continue a failed run while preserving its workspace and original logs:

~~~bash
conda run -n panta-env python evaluation/agent_baselines/openhands_runner.py \
  --project JacksonXml-5f --class ToXmlGenerator \
  --model-profile deepseek-v4.1-flash \
  --repair-run-dir evaluation/result-files/openhands/JacksonXml-5f/ToXmlGenerator/<initial-run-id> \
  --max-iterations 12 --timeout-seconds 600
~~~

The continuation gets the prior Surefire failure counts and can inspect the
full XML reports. It writes a separate run under repairs/ and updates the
initial run.json with the latest metrics and both run paths.

The default run directory is
evaluation/result-files/openhands/<project>/<class>/<UTC timestamp>/. It
contains the copied workspace/, task, OpenHands JSONL events, worker logs,
final Maven log, and run.json with final JaCoCo and Surefire metrics.

## Aider one-case run

Aider is installed outside `panta-env`; the runner invokes it inside the same
isolated Maven/Java 8 container used by OpenHands. Aider reads the focal source
and can edit only the generated test file. The model profile's LiteLLM
`extra_body` is passed through Aider's model settings file, and the generated
Maven command removes the API key from the test process environment.

~~~bash
uv tool install aider-chat==0.86.2 --python 3.12
export DEEPSEEK_API_KEY=...
cd CogPath
conda run -n panta-env python evaluation/agent_baselines/aider_runner.py \
  --project JacksonXml-5f --class ToXmlGenerator \
  --model-profile deepseek-v4.1-flash \
  --aider-executable "$(command -v aider)" --timeout-seconds 900
~~~

Continue a failed Aider run from its copied workspace:

~~~bash
conda run -n panta-env python evaluation/agent_baselines/aider_runner.py \
  --project JacksonXml-5f --class ToXmlGenerator \
  --model-profile deepseek-v4.1-flash \
  --aider-executable "$(command -v aider)" \
  --repair-run-dir evaluation/result-files/aider/JacksonXml-5f/ToXmlGenerator/<run-id>
~~~

The adapter writes Aider's JSONL usage events and a model metadata file.
DeepSeek documents a 1,048,576-token context and a 393,216-token maximum
output; this smoke runner caps Aider responses at 8,192 tokens and chat history
at 32,768 tokens. The metadata schema follows [Aider's advanced model
settings](https://aider.chat/docs/config/adv-model-settings.html), and the
limits follow [DeepSeek's API model list](https://api-docs.deepseek.com/api/list-models/).

## Isolation and measurement

The OpenHands SDK worker runs inside maven:3.9.9-eclipse-temurin-8. Only the
copied subject, that run's logs/config, and the read-only OpenHands Python
environment are mounted. The model key is removed from the worker environment
before it starts agent shell tools. Maven dependencies are downloaded into the
throwaway workspace; the host Maven cache is not mounted into the agent.

The runner's final verification is mvn clean package -Dtest=<Class>Test in
the copied project. It extracts the focal class's line/branch coverage from
target/jacoco/jacoco.csv, and test counts from Surefire XML. Agent completion,
Maven success, generated tests, coverage, and tokens are separate outcomes;
the adapter does not interpret a clean agent exit as a successful test run.

This is an end-to-end agent baseline: OpenHands can inspect the complete copied
project, use shell/file tools, and iterate on tests. It is not a prompt-only
comparison with CogPath. The adapter intentionally has no dataset loop; create
an explicit manifest/runner extension only after the one-case protocol and
resource budget have been reviewed.

## First smoke-run record

The first DeepSeek V4.1 Flash run used `JacksonXml-5f::ToXmlGenerator`. OpenHands
created 94 tests, but the initial Maven run reported 4 failures and 26 errors.
After six repair continuations, the suite contained 83 passing tests and the
final JaCoCo report showed 76.92% line coverage and 85.65% branch coverage.
The initial failed run and all repair logs are retained under
`evaluation/result-files/openhands/JacksonXml-5f/ToXmlGenerator/`. Across the
initial run and repairs, recorded prompt usage was about 2.74 million tokens;
LiteLLM did not provide a cost estimate for this model ID. Treat the coverage
as a repaired-run result, not a one-shot result, and report the initial test
validity and repair usage alongside it. The failure reports included
unsupported generator operations and XML writes outside a root element.

## One-case comparison across three methods

All runs target `JacksonXml-5f::ToXmlGenerator` with the
`deepseek-v4.1-flash` profile and isolated subject copies. CogPath used four
iterations, one repair round per iteration, Constraint-Hints, and Backward
Slicing. Its run summary is in
`result-files/control_deepseek-v4.1-flash_constraints_bs_deepseek-v4.1-flash/`.
Aider 0.86.2 ran one generation session and two repair continuations; its final
summary is in `evaluation/result-files/aider/JacksonXml-5f/ToXmlGenerator/`.

| Result | OpenHands | Aider | CogPath |
| --- | ---: | ---: | ---: |
| Final line coverage | 76.92% | 48.93% | 14.74% |
| Final branch coverage | 85.65% | 43.98% | 10.19% |
| Passing tests in final measurement | 83 | 21 | 12 of 60 validation attempts |
| Failures before final pass | 4 failures + 26 errors | 5 errors, then 1 error | 48 total (45 test failures, 3 compilation failures) |
| Runner-reported tokens | 2,799,976 | 873,975 | 217,557 |
| Repair budget | 6 continuation runs | 2 continuation runs | 1 repair round per CogPath iteration |

This is a debugging pilot, not a controlled performance result. OpenHands had
Aider's final passing suite contains 21 tests after two repair continuations.
Its initial agent session used 717,751 prompt tokens; two repair sessions used
about 75k tokens each. The first session did not yet have the chat-history cap
now supported by the runner, so treat its token total as an upper-bound pilot
measurement. Two earlier adapter-debug runs are retained separately and are
excluded from this selected-run total.

The test counts describe different things: OpenHands and Aider report their
passing final suites after repair, while CogPath's summary aggregates generated
test validations across iterations. OpenHands had six continuation runs, Aider
had two, and CogPath stopped after four iterations. Token counts are the
runners' reported prompt-plus-completion totals; cache-read tokens are a subset
of OpenHands prompt tokens and are not added twice. This pilot suggests that
agentic generation can reach higher coverage on this class, with more model
usage and repair, but it is not a controlled performance conclusion. A fair
comparison needs an agreed budget/repair policy, repeated runs, and matched
reporting of valid tests, wall time, tokens, and coverage.
