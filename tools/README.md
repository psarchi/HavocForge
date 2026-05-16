# Havocforge Tools

Developer tools for working with the Havocforge.

## json_to_schema.py

Translate JSON example data to YAML schema format.

### Installation

No additional dependencies needed - uses standard library + PyYAML (already in requirements.txt).

### Usage

**Basic usage (single object):**
```bash
python tools/json_to_schema.py example.json > schema.yaml
```

**From stdin:**
```bash
curl https://api.example.com/data | python tools/json_to_schema.py > schema.yaml
```

**Array inference (analyze multiple samples):**
```bash
python tools/json_to_schema.py examples.json --infer-arrays --sample-size 100
```

**Write to file:**
```bash
python tools/json_to_schema.py example.json -o schemas/my_schema.yaml
```

### Examples

**Input JSON:**
```json
{
  "user_id": 12345,
  "email": "user@example.com",
  "active": true,
  "score": 95.5,
  "tags": ["premium", "verified"],
  "profile": {
    "name": "John Doe",
    "joined": "2024-01-01"
  }
}
```

**Output YAML Schema:**
```yaml
type: object
fields:
  user_id:
    type: int
    min: 12345
    max: 12345
  email:
    type: string
    string_type: email
  active:
    type: bool
  score:
    type: float
    min: 95.5
    max: 95.5
    precision: 2
  tags:
    type: array
    min_items: 2
    max_items: 2
    child:
      type: string
  profile:
    type: object
    fields:
      name:
        type: string
      joined:
        type: string
```

**Array Inference Example:**

Input (array of objects):
```json
[
  {"id": 1, "name": "Alice", "score": 85},
  {"id": 2, "name": "Bob", "score": 92},
  {"id": 3, "name": "Charlie", "score": 78}
]
```

Command:
```bash
python tools/json_to_schema.py data.json --infer-arrays
```

Output (merged schema from all samples):
```yaml
type: object
fields:
  id:
    type: int
    min: 1
    max: 3
  name:
    type: string
  score:
    type: int
    min: 78
    max: 92
```

### Options

- `--infer-arrays`: Analyze multiple array items to infer schema (expands min/max ranges)
- `--sample-size N`: Number of array items to sample (default: 10)
- `-o FILE`: Write output to file instead of stdout

### Type Detection

The tool automatically detects:

- **Numbers**: `int` or `float` with min/max ranges
- **Booleans**: `bool`
- **Strings**:
  - Email addresses → `string_type: email`
  - URLs → `string_type: url`
  - Numeric strings → `regex: ^\d+$`
  - Generic → `type: string`
- **Arrays**: Infers child type from first item (or all items with `--infer-arrays`)
- **Objects**: Recursively processes nested fields
- **Null values**: Wraps in `maybe` type with `p_null: 0.5`

### Post-Processing

The generated schema is a starting point. You'll likely want to:

1. **Adjust ranges**: Expand `min`/`max` for realistic data generation
2. **Add string types**: Change to `uuid4`, `city`, `word`, etc.
3. **Add templates**: Use `template: "USER-{nnnn}"` for formatted strings
4. **Tune probabilities**: Adjust `p_null` for maybe fields
5. **Add constraints**: Add validation rules specific to your use case

### Tips

- Use `--infer-arrays` when you have multiple examples to get better min/max ranges
- Increase `--sample-size` for large datasets to capture more variation
- The tool is best for bootstrapping - manual refinement is expected
- Use with real API responses to quickly scaffold schemas
