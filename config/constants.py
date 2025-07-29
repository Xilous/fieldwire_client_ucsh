"""Constants for Fieldwire API."""

import re
import yaml
import os
from pathlib import Path

# Get the directory where this constants.py file is located
_CONFIG_DIR = Path(__file__).parent

def _load_yaml_file(filename):
    """Load a YAML file from the config directory."""
    file_path = _CONFIG_DIR / filename
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found: {file_path}")
    except yaml.YAMLError as e:
        raise ValueError(f"Error parsing YAML file {file_path}: {e}")

def _load_hardware_filters():
    """Load hardware filters from YAML file."""
    data = _load_yaml_file('hardware_filters.yaml')
    return data

def _load_fc_checklist_items():
    """Load FC checklist items from YAML file."""
    data = _load_yaml_file('fc_checklist_items.yaml')
    return data.get('items', [])

# Enhanced pattern matching functions
def check_whole_word_match(term, text):
    """Check if term exists as a complete word in text."""
    # Convert term to string if it's not already (safety for YAML parsing)
    term_str = str(term).lower()
    pattern = r'\b' + re.escape(term_str) + r'\b'
    return bool(re.search(pattern, text.lower()))

def check_enhanced_conditions(text, conditions, exclusions=None):
    """
    Enhanced condition checking with whole word matching and exclusions.
    
    Args:
        text: The text to check
        conditions: List of condition dictionaries with 'any', 'all', 'none' keys
        exclusions: Optional list of exclusion terms (contains matching)
    
    Returns:
        bool: True if text matches any condition set and no exclusions
    """
    # Check exclusions first (if any) - these use "contains" matching
    if exclusions:
        for exclusion_term in exclusions:
            if exclusion_term.lower() in text.lower():
                return False
    
    # Check conditions using existing logic but with whole word matching
    text_lower = text.lower()
    for condition_set in conditions:
        if 'any' in condition_set:
            any_match = any(check_whole_word_match(term, text_lower) for term in condition_set['any'])
            if not any_match:
                continue
        if 'all' in condition_set:
            all_match = all(check_whole_word_match(term, text_lower) for term in condition_set['all'])
            if not all_match:
                continue
        if 'none' in condition_set:
            none_match = not any(check_whole_word_match(term, text_lower) for term in condition_set['none'])
            if not none_match:
                continue
        return True
    return False

def validate_hardware_filters():
    """Validate HARDWARE_FILTERS configuration at startup."""
    errors = []
    warnings = []
    
    for hardware_type, config in HARDWARE_FILTERS.items():
        # Check required fields
        if 'conditions' not in config:
            errors.append(f"{hardware_type}: Missing 'conditions' field")
            continue
            
        # Validate conditions structure
        conditions = config['conditions']
        if not isinstance(conditions, list):
            errors.append(f"{hardware_type}: 'conditions' must be a list")
            continue
            
        for i, condition in enumerate(conditions):
            if not isinstance(condition, dict):
                errors.append(f"{hardware_type}: condition {i} must be a dictionary")
                continue
                
            # Check for valid keys
            valid_keys = {'any', 'all', 'none'}
            invalid_keys = set(condition.keys()) - valid_keys
            if invalid_keys:
                errors.append(f"{hardware_type}: condition {i} has invalid keys: {invalid_keys}")
            
            # Check term types in condition lists
            for condition_type in ['any', 'all', 'none']:
                if condition_type in condition:
                    terms = condition[condition_type]
                    if not isinstance(terms, list):
                        errors.append(f"{hardware_type}: condition {i} '{condition_type}' must be a list")
                        continue
                    
                    for j, term in enumerate(terms):
                        if not isinstance(term, (str, int, float)):
                            warnings.append(f"{hardware_type}: condition {i} '{condition_type}' term {j} has unexpected type: {type(term)}")
                        elif isinstance(term, (int, float)):
                            warnings.append(f"{hardware_type}: condition {i} '{condition_type}' term '{term}' is numeric - consider quoting in YAML if it should be a string")
        
        # Validate exclusions if present
        if 'exclusions' in config:
            exclusions = config['exclusions']
            if not isinstance(exclusions, list):
                errors.append(f"{hardware_type}: 'exclusions' must be a list")
            else:
                for j, term in enumerate(exclusions):
                    if not isinstance(term, (str, int, float)):
                        warnings.append(f"{hardware_type}: exclusion {j} has unexpected type: {type(term)}")
        
        # Validate create_items if present
        if 'create_items' in config:
            create_items = config['create_items']
            if not isinstance(create_items, list):
                errors.append(f"{hardware_type}: 'create_items' must be a list")
            else:
                for j, item in enumerate(create_items):
                    if not isinstance(item, str):
                        errors.append(f"{hardware_type}: create_items {j} must be a string, got {type(item)}")
    
    # Report warnings
    if warnings:
        print("Validation warnings:")
        for warning in warnings:
            print(f"  ⚠️  {warning}")
        print()
    
    # Report errors
    if errors:
        raise ValueError(f"Hardware filter validation failed:\n" + "\n".join(errors))
    
    print("Hardware filters validation passed!")

# Load configuration data from YAML files
try:
    HARDWARE_FILTERS = _load_hardware_filters()
    FC_CHECKLIST_ITEMS = _load_fc_checklist_items()
except Exception as e:
    print(f"Error loading configuration from YAML files: {e}")
    print("Please ensure hardware_filters.yaml and fc_checklist_items.yaml exist in the config directory.")
    raise

# Validate configuration when module is imported
try:
    validate_hardware_filters()
except Exception as e:
    print(f"Warning: Hardware filter validation failed: {e}")
    print("Using filters with potential issues. Please review configuration.")