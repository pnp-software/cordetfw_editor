# The status of an item with a history
HISTORY_STATUS = (
    ("DEL","Deleted"),
    ("OBS","Obsolete"),
    ("CNF","Confirmed"),
    ("MOD","Modified"),
    ("NEW","New"),
)

# The specification item categories
SPEC_ITEM_CAT = (
    ("Requirement","An application requirement"),
    ("DataItemType","a data item type"),
    ("EnumItem","An enumerated item"),
    ("DataItem","a data item"),
    ("Model","A behavioural model for an application feature"),
    ("Service","A cordet service"),
    ("Packet","A packet implementing a service command or report"),
    ("PacketPar","A parameter in a packet"),
    ("PacketBehaviour","The behaviour associated to a packet in an application"),
    ("VerItem","A verification item"),
)

# The kind of a requirement
REQ_KIND = (
    ("STD","Standard Requirement"),
    ("CNS","Constraint Requirement"),
    ("AP","Adaptation Point Requirement"),
)

# The kind of a data item
DI_KIND = (
    ("CNS","Constant"),
    ("PAR","Configuration Parameter"),
    ("VAR","Global Variable"),
    ("PCK","Packet Parameter"),
)

# The kind of a data item type
DIT_KIND = (
    ("ENUM","Enumerated"),
    ("NOT_ENUM","Not Enumerated"),
)

# The kind of a behavioural model
MODEL_KIND = (
    ("SM","State Machine"),
    ("PR","Procedure"),
)

# The kind of a packet
PCKT_KIND = (
    ("REP","Report"),
    ("CMD","Command"),
)

# The role of a parameter in a packet
PCKT_PAR_KIND = (
    ("DISC","Discriminant"),
    ("HK","Housekeeping Parameter"),
    ("PCK","Packet Parameter"),
)

# The role played by an application for a packet
PCKT_APP_KIND = (
    ("PROV","Service Provider"),
    ("USER","Service User"),
)

# The kind of a verification item
VER_ITEM_KIND = (
    ("TST","Test Case"),
    ("REV","Review Item"),
    ("ANA","Analysis Item"),
)

# The verification method of a requirement
REQ_VER_METHOD = (
    ("TST","Verification by Test"),
    ("ANA","Verification by Analysis"),
    ("REV","Verification by Review"),
)

# The verification status of a verification item
VER_STATUS = (
    ("OPEN","Verification Still Open"),
    ("CLOSED","Verification Closed"),
)

