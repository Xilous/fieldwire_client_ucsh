# Hardware Filters Configuration Guide

This document explains how to edit and maintain the hardware filter configuration files in this directory.

## 📁 Configuration Files

- **`hardware_filters.yaml`** - Defines hardware detection and processing rules
- **`fc_checklist_items.yaml`** - Defines standard checklist items for FC (Frame Check) tasks

## 🔧 Hardware Filters Structure

Each hardware type in `hardware_filters.yaml` follows this structure:

```yaml
HARDWARE_TYPE_NAME:
  conditions:           # Required: List of condition sets
    - any: [...]       # Match ANY of these terms
    - all: [...]       # Match ALL of these terms
    - all: [...]
      none: [...]      # Match first terms but NOT these terms
  exclusions: [...]    # Optional: Reject if ANY found anywhere
  create_items:        # Optional: Additional checklist items to create
    - 'Item Name 1'
    - 'Item Name 2'
```

## 🎯 Understanding Conditions

### **Condition Types**

#### `any` - OR Logic
Matches if **ANY** of the listed terms are found as whole words in the text.

```yaml
conditions:
  - any: ['card', 'reader', 'keypad']
```
- ✅ Matches: "card reader device", "keypad entry", "card system"
- ❌ Doesn't match: "cardboard", "hardcard", "keyboard"

#### `all` - AND Logic  
Matches if **ALL** of the listed terms are found as whole words in the text.

```yaml
conditions:
  - all: ['electronic', 'lock']
```
- ✅ Matches: "electronic lock system", "lock electronic device"
- ❌ Doesn't match: "electronic device", "lock only"

#### `none` - NOT Logic
Used with `all` or `any` to exclude certain terms. Matches the primary terms but rejects if any of the `none` terms are found.

```yaml
conditions:
  - all: ['mag', 'lock']
    none: ['filler', 'bracket']
```
- ✅ Matches: "mag lock device", "magnetic lock system"
- ❌ Doesn't match: "mag lock filler plate", "mag lock bracket assembly"

### **Multiple Condition Sets**
You can have multiple condition sets - if **ANY** condition set matches, the hardware type matches.

```yaml
conditions:
  - any: ['dps']                    # Matches if contains "dps"
  - all: ['door', 'contact']        # OR if contains both "door" and "contact"  
  - all: ['door', 'position']       # OR if contains both "door" and "position"
```

## 🚫 Exclusions

Exclusions provide a simple way to reject matches based on substring matching (not whole words).

```yaml
exclusions: ['BPS', 'cabinet']
```

- **How it works**: If the text contains ANY exclusion term anywhere (even within other words), the match is rejected
- **Example**: Text "electronic lock BPSafe device" would be rejected because it contains "BPS"
- **Use case**: Broad exclusions where you want to avoid certain contexts

### **Exclusions vs. `none` Conditions**

| Feature | `exclusions` | `none` conditions |
|---------|--------------|-------------------|
| **Matching** | Substring (anywhere) | Whole word only |
| **Scope** | Applies to entire hardware type | Applies to specific condition set |
| **Use for** | Broad exclusions | Specific logical exclusions |

## 📝 Create Items

Optional list of additional checklist items that get added to UCA tasks when this hardware type is detected.

```yaml
create_items:
  - 'Hardware Cables Pulled'
  - 'Hardware Wires Terminated'  
  - 'Hardware Installed'
  - 'Hardware Tested'
```

**Note**: Always quote strings to ensure they're treated as text, not parsed as other data types.

## ➕ Adding New Hardware Types

1. **Choose a descriptive name** (use ALL CAPS with spaces or underscores)
2. **Define conditions** (at least one condition set required)
3. **Add exclusions if needed** (optional)
4. **Define create_items if needed** (optional)

### Example: Adding a new "PROXIMITY SENSOR" hardware type

```yaml
PROXIMITY SENSOR:
  conditions:
    - any: ['proximity', 'prox']
    - all: ['sensor', 'detect']
  exclusions: ['motion']  # Exclude motion sensors
  create_items:
    - 'Proximity Sensor Cables Pulled'
    - 'Proximity Sensor Installed'
    - 'Proximity Sensor Tested'
```

## 🔍 Real-World Examples

### **Simple Matching**
```yaml
BOLLARD:
  conditions:
    - any: ['bollard']  # Just look for the word "bollard"
  create_items:
    - 'Bollard Cables Pulled'
    - 'Bollard Installed'
```

### **Complex Matching with Exclusions**
```yaml
ELECTRONIC LOCK:
  conditions:
    - all: ['elec', 'lock']          # Electronic lock
    - all: ['fail', 'secure']        # Fail secure lock
    - any: ['LPM190eu']              # Specific model number
  exclusions: ['BPS']                # Exclude BPS context
  create_items:
    - 'Electronic Lock Cables Pulled'
    - 'Electronic Lock Tested'
```

### **Multiple Condition Sets**
```yaml
DOOR CONTACT:
  conditions:
    - any: ['dps']                   # DPS abbreviation
    - all: ['door', 'con']           # "door con" (contact)
    - all: ['door', 'pos']           # "door pos" (position)
  create_items:
    - 'Door Contact Installed'
    - 'Door Contact Tested'
```

### **Detection Only (No Additional Items)**
```yaml
CARD READER:
  conditions:
    - any: ['card', 'reader', 'keypad']
  # No create_items - just detect and copy original items
```

## ⚠️ Important Rules

### **String Quoting**
- **Always quote all string values** to prevent YAML parsing issues
- ✅ Good: `['53', '54', 'electronic', 'lock']`
- ❌ Bad: `[53, 54, electronic, lock]` (numbers become integers, unquoted words might be keywords)

### **Word Boundary Matching**
- All condition terms use whole-word matching
- `'card'` matches "card reader" but not "cardboard"
- Use exclusions for substring-based rejections

### **Case Insensitive**
- All matching is case-insensitive
- `'Electronic'`, `'electronic'`, and `'ELECTRONIC'` all match the same way

## 🛠️ Testing Your Changes

After editing the configuration:

1. **Syntax validation**: Import will validate structure automatically
2. **Test matching**: Use the enhanced functions to test specific cases
3. **Check warnings**: The system will warn about potential issues

```python
# Test your changes
from config.constants import HARDWARE_FILTERS
print("Configuration loaded successfully!")
```

## 🚨 Troubleshooting

### **Common Errors**

**"Configuration file not found"**
- Ensure `hardware_filters.yaml` exists in the `config/` directory
- Check file permissions

**"Error parsing YAML file"**
- Check YAML syntax (indentation, quotes, colons)
- Ensure all strings are quoted
- Validate YAML structure online if needed

**"AttributeError: 'int' object has no attribute 'lower'"**
- You have unquoted numbers that should be strings
- Quote all values: `['53', '54']` not `[53, 54]`

### **Validation Warnings**

The system will warn about:
- Numeric values that might need quoting
- Missing required fields
- Invalid data types
- Structural issues

## 📋 FC Checklist Items

The `fc_checklist_items.yaml` file is simpler:

```yaml
items:
  - 'RH Plumb'
  - 'LH Plumb'  
  - 'Header'
  - 'Wall Painted'
  # Add new items here
```

Just add new checklist items to the `items` list, ensuring each item is quoted as a string.

## 🔄 Best Practices

1. **Test thoroughly** - Try your conditions with real-world text examples
2. **Use exclusions sparingly** - They apply broadly and can have unexpected effects
3. **Be specific** - Prefer precise conditions over broad ones
4. **Document complex logic** - Add comments for non-obvious conditions
5. **Quote everything** - Maintain consistency and avoid parsing issues
6. **Start simple** - Begin with basic conditions and add complexity as needed

## 📞 Getting Help

If you encounter issues:
1. Check the validation messages when importing the configuration
2. Test your conditions with sample text
3. Review this documentation for examples
4. Ensure all values are properly quoted as strings

---

*This configuration system provides powerful and flexible hardware detection while maintaining safety and ease of use.* 