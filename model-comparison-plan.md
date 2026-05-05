# Model Comparison Plan: AI Slide Deck Generation

## Objective

Generate an identical PowerPoint slide deck presentation using multiple AI models to compare:
1. **Output quality** — design, consistency, visual appeal
2. **Accuracy** — content correctness, adherence to plan
3. **Code quality** — Python/pptx code readability, robustness
4. **Execution time** — how long each model takes to complete
5. **Prompt comprehension** — how well each model followed detailed specifications

---

## Task Definition

**Input**: `c:\dev\local-llm-phi4\slide-deck-plan.md` (comprehensive 20-slide plan with detailed design specs)

**Output per model**:
- `slide-deck-{MODEL_NAME}.pptx` — PowerPoint file with 20 slides
- `generate-{MODEL_NAME}.py` — Python script used to generate the deck
- Timing metadata and notes on generation

**Success criteria**:
- File size > 50 KB (indicates actual content, not placeholder)
- Opens successfully in PowerPoint or LibreOffice Impress
- Contains all 20 slides with correct titles
- Applies dark theme (#1e2030 background, #00d4ff accents)
- Tables render correctly with alternating row shading
- Code blocks are formatted with monospace font and dark background
- Diagrams are present and aligned (slides 7, 8, 11)

---

## Models to Test

### Model 1: Claude Sonnet 4.6
- **Provider**: Anthropic via GitHub Copilot CLI
- **Context window**: 200k tokens
- **Expected strengths**: Long-form instructions, complex architecture diagrams, code quality
- **Output file**: `c:\dev\local-llm-phi4\slide-deck-claude-sonnet.pptx`
- **Generator script**: `c:\dev\local-llm-phi4\generate-claude-sonnet.py`

### Model 2: GPT-4 Turbo or GPT-4o
- **Provider**: OpenAI API (requires API key)
- **Context window**: 128k tokens
- **Expected strengths**: Creative design choices, consistency across slides
- **Output file**: `c:\dev\local-llm-phi4\slide-deck-gpt4.pptx`
- **Generator script**: `c:\dev\local-llm-phi4\generate-gpt4.py`

### Model 3: Claude Haiku 4.5 (Optional / Fallback)
- **Provider**: Anthropic via GitHub Copilot CLI (current model)
- **Context window**: 200k tokens
- **Expected strengths**: Speed, conciseness
- **Output file**: `c:\dev\local-llm-phi4\slide-deck-haiku.pptx`
- **Generator script**: `c:\dev\local-llm-phi4\generate-haiku.py`

---

## Generation Process Per Model

### Step 1: Read the Plan
Each agent will:
- Read `c:\dev\local-llm-phi4\slide-deck-plan.md` in its entirety
- Extract the 20 slide specifications with design requirements
- Understand colour scheme, fonts, layout constraints

### Step 2: Generate Python Script
Each agent will:
- Write a complete `python-pptx`-based script
- Include all 20 slides with content, styling, and positioning
- Use the exact colour hex codes specified (#1e2030, #00d4ff, etc.)
- Apply fonts: Calibri for titles/body, Courier New for code
- Add callout boxes, tables, and diagrams where specified
- Include error handling and verification

### Step 3: Execute Script
Each agent will:
- Save the script to its assigned filename
- Execute the script: `py generate-{MODEL}.py`
- Verify the output file exists and is > 50 KB
- Check that the file is a valid PPTX (can be opened)

### Step 4: Collect Metadata
Each agent will report:
- File size (bytes)
- Script line count
- Time to generate
- Any deviations from spec or design choices made
- Notes on python-pptx challenges encountered

---

## Comparison Criteria

| Criterion | How to Measure | Weight |
|---|---|---|
| **Design fidelity** | Visual inspection: colours, fonts, spacing match spec? | 25% |
| **Content accuracy** | All 20 slides present with correct text, no truncation? | 20% |
| **Code quality** | Script is readable, maintainable, handles edge cases? | 15% |
| **Consistency** | Styling consistent across all slides? | 15% |
| **Completeness** | Diagrams, tables, code blocks all rendered? | 15% |
| **Speed** | Time to generate (lower is better, but not priority) | 10% |

---

## Post-Generation Analysis

After all models complete:

1. **Visual inspection** — open all 3 decks side-by-side, compare:
   - Title slide appearance
   - Diagram rendering (slide 7 flow, slide 8 architecture)
   - Table formatting (slide 4, 6, 12, 19)
   - Code block appearance (slides 10, 13, 14, 18)

2. **Content audit** — verify each slide has:
   - Correct title
   - No missing bullet points or text
   - Callout boxes present and formatted
   - Speaker notes (where specified)

3. **File characteristics**:
   - File size comparison (indicates efficiency)
   - Ability to edit in PowerPoint (no corruption)
   - Font substitution issues (did fonts render as intended?)

4. **Code review**:
   - Which script is more readable?
   - Which handles tables/diagrams more elegantly?
   - Which made better design choices when ambiguous?

5. **Summary report** — create `model-comparison-results.md` with:
   - Winner per criterion (or ties)
   - Design choices that differed
   - Recommendations for future use

---

## Technical Notes

### Python-pptx Version
All models will use `python-pptx` v0.6.24 (or latest stable).

### Required Imports (standardized)
```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
```

### Colour Palette (no deviations)
```python
DARK_BG = RGBColor(0x1e, 0x20, 0x30)        # #1e2030
ACCENT = RGBColor(0x00, 0xd4, 0xff)        # #00d4ff (cyan)
TEXT_WHITE = RGBColor(0xff, 0xff, 0xff)    # #ffffff
TEXT_GREY = RGBColor(0xe0, 0xe0, 0xe0)    # #e0e0e0
CALLOUT_BG = RGBColor(0x2a, 0x2d, 0x45)    # #2a2d45
CODE_BG = RGBColor(0x0d, 0x11, 0x17)       # #0d1117
CODE_TEXT = RGBColor(0xc9, 0xd1, 0xd9)     # #c9d1d9
```

### Slide Size (all models)
- 16:9 widescreen: 13.33 × 7.5 inches

---

## Deliverables

**For each model:**
1. PowerPoint file: `slide-deck-{MODEL_NAME}.pptx`
2. Generator script: `generate-{MODEL_NAME}.py`
3. Metadata file: `{MODEL_NAME}-metadata.txt` (file size, line count, generation time)

**Summary report:**
- `model-comparison-results.md` (analysis and recommendations)

**All files** go to: `c:\dev\local-llm-phi4\`

---

## Success Definition

✅ **Success**: 
- All 3 models generate valid, opening .pptx files with 20 slides
- Each deck is >50 KB and contains the expected content
- Visual inspection shows consistent styling across models
- At least 2/3 models render diagrams and tables correctly

⚠️ **Partial success**: 
- 2/3 models succeed; 1 fails or degrades
- Files open but have styling/rendering issues

❌ **Failure**: 
- <2 models complete the task
- Generated files are corrupted or <50 KB

---

## Execution Notes

- Each model receives the **identical prompt** (detailed specifications from plan.md)
- **No human intervention** during generation — purely autonomous
- Models may make different design choices for ambiguous aspects (these are noted, not failures)
- If a model encounters a python-pptx limitation, document it and offer a workaround
- Track total execution time for each model (agent initialization + script execution)

---

## Next Steps

1. ✅ Create this plan.md (you are here)
2. Launch 3 background agents, each with a different model:
   - Agent 1: Claude Sonnet 4.6
   - Agent 2: GPT-4 Turbo / GPT-4o (via OpenAI)
   - Agent 3: Claude Haiku 4.5 (optional)
3. Wait for all agents to complete
4. Collect outputs and metadata
5. Perform visual and content inspection
6. Generate comparison report
7. Commit all files and report to GitHub

