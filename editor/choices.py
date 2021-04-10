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
    ("AdaptPoint","An adaptation point"),
    ("DataItemType","A non-enumerated data item type"),
    ("EnumType","An enumerated data item type"),
    ("EnumValue","An enumerated item"),
    ("DataItem","A data item"),
    ("Model","A behavioural model for an application feature"),
    ("Service","A cordet service"),
    ("Packet","A packet implementing a service command or report"),
    ("DerPacket","A derived packet"),
    ("PacketPar","A parameter in a packet"),
    ("InCommand","The behaviour associated to an incoming service command"),
    ("InReport","The behaviour associated to an incoming service report"),
    ("OutComponent","The behaviour associated to an out-going service command or report"),
    ("VerItem","A verification item"),
    ("VerLink","A verification link"),
)

# The kind of a requirement
REQ_KIND = (
    ("STD","Standard Requirement"),
    ("CNS","Constraint Requirement"),
    ("AP","Adaptation Point Requirement"),
)

# The kind of adaptation point
AP_KIND = (
    ("SPC","Specification Level"),
    ("IMP","Implementation Level"),
)

# The role of a project user
USER_ROLE = (
    ("RO","Read-Only"),
    ("RW","Read-Write"),
)

# The kind of a data item
DI_KIND = (
    ("CNS","Constant"),
    ("PAR","Configuration Parameter"),
    ("VAR","Global Variable"),
    ("PCK","Packet Parameter"),
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


