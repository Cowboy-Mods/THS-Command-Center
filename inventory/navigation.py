NAVIGATION = [
    ("Overview", [("Dashboard", "/")]),
    (
        "Filament",
        [
            ("Inventory", "/inventory/filament"),
            ("AMS Units", "/inventory/filament/ams"),
        ],
    ),
    (
        "Materials",
        [
            ("General Materials", "/modules/general-materials"),
            ("Leather", "/modules/leather"),
            ("Engraving Materials", "/modules/engraving-materials"),
            ("Wood and Sheet Stock", "/modules/wood-sheet-stock"),
        ],
    ),
    (
        "Parts and Components",
        [
            ("Mechanical Parts", "/modules/mechanical-parts"),
            ("RC Components", "/modules/rc-components"),
            ("Electronics", "/modules/electronics"),
            ("Connectors and Wiring", "/modules/connectors-wiring"),
            ("Motors and Servos", "/modules/motors-servos"),
            ("Bearings", "/modules/bearings"),
            ("Hardware and Fasteners", "/modules/hardware-fasteners"),
        ],
    ),
    (
        "Tools and Equipment",
        [
            ("Hand Tools", "/modules/hand-tools"),
            ("Power Tools", "/modules/power-tools"),
            ("Printers and Machines", "/modules/printers-machines"),
            ("Test Equipment", "/modules/test-equipment"),
            ("Shop Equipment", "/modules/shop-equipment"),
        ],
    ),
    (
        "Consumables",
        [
            ("Adhesives", "/modules/adhesives"),
            ("Paints and Finishes", "/modules/paints-finishes"),
            ("Cleaning Supplies", "/modules/cleaning-supplies"),
            ("Safety Supplies", "/modules/safety-supplies"),
            ("Packaging and Shipping", "/modules/packaging-shipping"),
        ],
    ),
    (
        "Planning and Operations",
        [
            ("Projects", "/modules/projects"),
            ("Bills of Materials", "/modules/bills-of-materials"),
            ("Build Readiness", "/modules/build-readiness"),
            ("Reservations", "/modules/reservations"),
            ("Purchase Orders", "/modules/purchase-orders"),
            ("Shopping List", "/modules/shopping-list"),
            ("Reorder Recommendations", "/modules/reorder-recommendations"),
            ("Suppliers", "/modules/suppliers"),
            ("Purchase History", "/modules/purchase-history"),
            ("Locations", "/modules/locations"),
            ("Maintenance", "/modules/maintenance"),
        ],
    ),
    (
        "Information and Control",
        [
            ("Reports", "/modules/reports"),
            ("Imports", "/modules/imports"),
            ("Integrations", "/modules/integrations"),
            ("Settings", "/modules/settings"),
            ("Tracking Policies", "/modules/tracking-policies"),
        ],
    ),
]

MODULES = {
    path.removeprefix("/modules/"): label
    for _, links in NAVIGATION
    for label, path in links
    if path.startswith("/modules/")
}


