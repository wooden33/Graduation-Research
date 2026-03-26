### Backward Slicing for Stubborn Coverage

Despite iterative test generation, some code branches remain persistently uncovered due to complex control flow dependencies or intricate input requirements. To address this challenge, we introduce a **Backward Slicing** strategy that leverages Large Language Models to analyze and overcome coverage plateaus.

#### Motivation

Traditional iterative test generation approaches may struggle with code paths that require specific precondition combinations, such as particular object states, complex control flow conditions, or mocked method return values. These "stubborn" uncovered branches often share common characteristics: they are located deep within nested conditionals, depend on intermediate computation results, or require precise input values that are difficult to infer from uncovered code alone.

#### Approach

Our backward slicing technique operates in two phases:

**Phase 1: Slice Extraction.** When the coverage improvement stagnates (i.e., no coverage increase for $\beta \times N$ consecutive iterations, where $\beta=0.6$ and $N$ is the maximum allowed iterations without improvement), the system triggers backward slicing analysis. For each uncovered code statement, an LLM is invoked to perform backward data-flow and control-flow analysis. The prompt includes:

- The uncovered code segment (target point)
- The complete source code of the focal method
- Dependency context (related classes and methods)

The LLM responds with a structured JSON containing:
- **backward_slice_code**: Minimal set of statements leading to the target
- **prerequisites**:
  - *input_values*: Required input parameters and their values
  - *object_states*: Object field states needed for execution
  - *method_mocks*: External method calls that must be mocked
  - *control_flow_logic*: Summary of the logical path required
- **test_hint**: Guidance for test case construction

**Phase 2: Test Generation.** Based on the extracted backward slices, a second LLM call generates targeted unit tests. Unlike general iterative generation that relies on coverage feedback, this phase directly incorporates the precise preconditions identified by the slice analysis, enabling precise navigation to previously unreachable code paths.

#### Triggering Condition

The backward slicing module is activated when:
$$\text{no\_coverage\_increase} \geq \beta \times \text{max\_no\_increase\_iterations}$$

where $\beta = 0.6$ by default. This ensures backward slicing is invoked only when conventional iterative approaches fail to make progress, balancing computational efficiency with coverage maximization.

#### Integration with Main Loop

Algorithm~\ref{alg:main} integrates backward slicing as follows: after the standard iterative test generation phase, if the triggering condition is met, the system invokes the backward slicer to analyze uncovered code. The generated slice-based tests are then validated, executed, and their coverage is measured in the same manner as regular generated tests. This seamless integration allows the system to recover from coverage plateaus without disrupting the overall test generation workflow.
