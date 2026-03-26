# Cogpath: Branch Conditions Guided Test Generation

Automated unit test generation using Large Language Models (LLMs) with branch condition analysis and backward slicing.

## Project Structure

```
.
├── defects4j-subjects-notests/       # defects4j projects without existing test suites
├── evaluation/                       # scripts and data for evaluation
│   ├── cogpath_results/              # evaluation results
│   ├── data/                         # statistics and evaluation results
│   └── *.py                          # evaluation scripts
├── result-files/                     # result reports for different LLMs and prompts
├── src/
│   └── cogpath/                      # Cogpath implementation
├── pyproject.toml                    # Poetry configuration
├── cogpath-env.yml                   # conda environment snapshot
└── README.md
```

## Quick Start

### Environment Setup

```bash
conda create --name cogpath python=3.11
conda activate cogpath
poetry install
```

### Configuration

Edit `src/cogpath/config.ini` to set:
- `model`: LLM model to use (e.g., `openrouter/openai/gpt-4o-mini`)
- `source_code_file`: Path to the source file to test
- `test_code_file`: Path to the test file to generate
- Target coverage and iteration parameters

### Running

```bash
# Set API key
export OPENAI_API_KEY='your-api-key'

# Run via poetry
poetry run cogpath

# Or directly
python -m cogpath.main
```

## Supported Models

- GPT-4o, GPT-4o-mini, GPT-5 series
- Claude 3.5, Claude 4 series
- Llama 3.x series
- Mistral series
- Qwen series
- DeepSeek V3

## Features

- **Branch-guided test generation**: Analyzes code coverage and branch conditions
- **Backward slicing**: Generates tests targeting specific slices of code
- **Constraint solving**: Uses LLMs to solve path constraints
- **Multiple prompt strategies**: Control, Symprompt, HITS modes
- **Automated test fixing**: Automatically fixes failed generated tests

## Evaluation

See `evaluation/README.md` for replication instructions.
