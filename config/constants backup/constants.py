"""Constants for Fieldwire API."""

# Hardware filters for UCA task processing
HARDWARE_FILTERS = {
    'ACTUATOR': {
        'conditions': [
            {'any': ['actuator']},
            {'all': ['hand', 'free']},
            {'all': ['wave', 'open']},
            {'all': ['push', 'button']}
        ],
        'create_items': [
            'Actuator Cables Pulled',
            'Actuator Wires Terminated',
            'Actuator Installed',
            'Actuator Tested'
        ]
    },
    'ADO': {
        'conditions': [
            {'any': ['sw200', 'ado', 'operator', 'omega', 'opener'],
             'none': ['supply', 'paddle', 'supplier']}
        ],
        'create_items': [
            'ADO Header',
            'ADO Motor/Controller',
            'ADO Arm',
            'ADO 120VAC Power',
            'ADO Tested',
        ]
    },
    'BOLLARD': {
        'conditions': [
            {'any': ['bollard']}
        ],
        'create_items': [
            'Bollard Cables Pulled',
            'Bollard Wires Terminated',
            'Bollard Installed'
        ]
    },
    'CARD READER': {
        'conditions': [
            {'any': ['card', 'reader', 'keypad'],
             'any': ['card reader', 'dk-12']}
        ]
    },
    'CONCEALED CLOSER': {
        'conditions': [
            {'all': ['concealed', 'closer']}
        ],
        'create_items': [
            'Concealed Closer Installed'
        ]
    },
    'DOOR CONTACT': {
        'conditions': [
            {'any': ['dps']},
            {'all': ['door', 'con']},
            {'all': ['door', 'pos']}
        ],
        'create_items': [
            'Door Contact Cables Pulled',
            'Door Contact Wires Terminated',
            'Door Contact Installed',
            'Door Contact Tested'
        ]
    },
    'ELECTRIC STRIKE': {
        'conditions': [
            {'all': ['elec', 'strike']}
        ],
        'create_items': [
            'Electric Strike Cables Pulled',
            'Electric Strike Wires Terminated',
            'Electric Strike Installed',
            'Electric Strike Tested'
        ]
    },
    'ELECTRONIC LOCK': {
        'conditions': [
            {'all': ['elec', 'lock'], 'none': ['BPS']},
            {'all': ['fail', 'secure']},
            {'all': ['elr'], 'none': ['BPS']},
            {'all': ['elec', 'lockset'], 'none': ['BPS']},
            {'any': ['sml-jeu-1076-ra-lc 711']},
            {'all': ['vingcard', 'rfid']},
            {'any': ['LPM190eu']}
        ],
        'create_items': [
            'Electronic Lock Cables Pulled',
            'Electronic Lock Wires Terminated',
            'Electronic Lock Installed',
            'Electronic Lock Tested'
        ]
    },
    'ELECTRONIC HOLDER': {
        'conditions': [
            {'all': ['elec', 'clos']},
            {'all': ['mag', 'hold']},
            {'any': ['eht']}
        ],
        'create_items': [
            'Electronic Holder Cables Pulled',
            'Electronic Holder Wires Terminated',
            'Electronic Holder Installed',
            'Electronic Holder Tested'
        ]
    },
    'EXIT DEVICE': {
        'conditions': [
            {'all': ['exit device'], 
             'any': ['53', '54', '55', '56', '57', '58', '59', 'teu', 'qel', 'e996l', 'm996l']}
        ],
        'create_items': [
            'Exit Device Cables Pulled',
            'Exit Device Wires Terminated',
            'Exit Device Tested'
        ]
    },
    'KEY SWITCH': {
        'conditions': [
            {'all': ['key', 'swit', 'mk2']}
        ],
        'create_items': [
            'Key Switch Cables Pulled',
            'Key Switch Wires Terminated',
            'Key Switch Installed',
            'Key Switch Tested'
        ]
    },
    'LATCH MONITOR': {
        'conditions': [
            {'all': ['key', 'swit', 'lm-1']}
        ],
        'create_items': [
            'Latch Monitor Cables Pulled',
            'Latch Monitor Wires Terminated',
            'Latch Monitor Tested'
        ]
    },
    'MAGLOCK': {
        'conditions': [
            {'all': ['mag', 'lock'], 
             'none': ['filler', 'signage', 'cylinder', 'bracket'],
             'any': ['m82fb', 'm82bd', 'm680ebd']}
        ],
        'create_items': [
            'Maglock Cables Pulled',
            'Maglock Wires Terminated',
            'Maglock Tested'
        ]
    },
    'OCCUPANCY INDICATOR': {
        'conditions': [
            {'all': ['occup', 'wc']}
        ],
        'create_items': [
            'Occupancy Indicator Cables Pulled',
            'Occupancy Indicator Wires Terminated',
            'Occupancy Indicator Installed',
            'Occupancy Indicator Tested'
        ]
    },
    'POWER SUPPLY': {
        'conditions': [
            {'all': ['power', 'supply']}
        ],
        'create_items': [
            'Power Supply Cables Pulled',
            'Power Supply Wires Terminated',
            'Power Supply Installed',
            'Power Supply Tested'
        ]
    },
    'POWER TRANSFER HINGE': {
        'conditions': [
            {'all': ['elec', 'hinge']},
            {'all': ['power', 'transfer']},
            {'all': ['elec', 'pivot']},
            {'any': ['atw', 'e-ml']}
        ],
        'create_items': [
            'Power Transfer Hinge Cables Pulled',
            'Power Transfer Hinge Wires Terminated',
            'Power Transfer Hinge Installed',
            'Power Transfer Hinge Tested'
        ]
    },
    'PUSH TO EXIT BUTTON': {
        'conditions': [
            {'all': ['push', 'exit']},
            {'all': ['exit', 'button']}
        ],
        'create_items': [
            'Push to Exit Button Cables Pulled',
            'Push to Exit Button Wires Terminated',
            'Push to Exit Button Installed',
            'Push to Exit Button Tested'
        ]
    },
    'PUSH TO LOCK': {
        'conditions': [
            {'all': ['ptl', 'wc']},
            {'all': ['wc', 'push', 'lock']}
        ],
        'create_items': [
            'Push to Lock Cables Pulled',
            'Push to Lock Wires Terminated',
            'Push to Lock Installed',
            'Push to Lock Tested'
        ]
    },
    'REMOTE RELEASE': {
        'conditions': [
            {'all': ['remote', 'release']}
        ],
        'create_items': [
            'Remote Release Wires Terminated',
            'Remote Release Installed',
            'Remote Release Tested'
        ]
    },
    'REX MOTION SENSOR': {
        'conditions': [
            {'any': ['REX']},
            {'all': ['request', 'exit']}
        ],
        'create_items': [
            'REX Motion Sensor Cables Pulled',
            'REX Motion Sensor Wires Terminated',
            'REX Motion Sensor Installed',
            'REX Motion Sensor Tested'
        ]
    },
    'SAFETY SENSOR': {
        'conditions': [
            {'all': ['safety', 'sensor']},
            {'any': ['superscan', 'presence', 'bodyguard', 'LZR']}
        ],
        'create_items': [
            'Safety Sensor Cables Pulled',
            'Safety Sensor Wires Terminated',
            'Safety Sensor Installed',
            'Safety Sensor Tested'
        ]
    },
    'SIP BOX': {
        'conditions': [
            {'any': ['sip', 's.i.p', 'surface box']}
        ],
        'create_items': [
            'SIP Box Cables Pulled',
            'SIP Box Wires Terminated',
            'SIP Box Installed',
            'SIP Box Tested'
        ]
    },
    'UWR KIT': {
        'conditions': [
            {'any': ['wec', 'wc1']}
        ],
        'create_items': [
            'UWR Kit Cables Pulled',
            'UWR Kit Wires Terminated',
            'UWR Kit Installed',
            'UWR Kit Tested'
        ]
    }
}

# Checklist items for FC tasks
FC_CHECKLIST_ITEMS = [
    "RH Plumb",
    "LH Plumb",
    "RH Plumb and Plane",
    "LH Plumb and Plane",
    "Header",
    "Flooring Complete",
    "Wall Painted",
    "Frame Painted",
    "Rework Required",
    "ADO Backing"
]