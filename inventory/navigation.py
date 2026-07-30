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
        "Projects",
        [
            ("Project List", "/projects"),
            ("Print Registry", "/prints"),
            ("Bills of Materials", "/modules/bills-of-materials"),
            ("Build Readiness", "/modules/build-readiness"),
            ("Reservations", "/modules/reservations"),
        ],
    ),
    (
        "Orders and Purchasing",
        [
            ("Orders", "/orders"),
            ("Shopping List", "/modules/shopping-list"),
            ("Reorder Recommendations", "/modules/reorder-recommendations"),
            ("Suppliers", "/modules/suppliers"),
            ("Purchase History", "/modules/purchase-history"),
        ],
    ),
    (
        "Locations",
        [
            ("Rooms", "/modules/rooms"),
            ("Shelves and Racks", "/modules/shelves-racks"),
            ("Cabinets and Drawers", "/modules/cabinets-drawers"),
            ("Mobile or Job Locations", "/modules/mobile-job-locations"),
        ],
    ),
    (
        "Maintenance",
        [
            ("Equipment Maintenance", "/maintenance"),
            ("Printer Maintenance", "/modules/printer-maintenance"),
            ("Service History", "/modules/service-history"),
            ("Maintenance Supplies", "/modules/maintenance-supplies"),
        ],
    ),
    (
        "Reports",
        [
            ("Audit Mode", "/audit"),
            ("Inventory Summary", "/modules/inventory-summary"),
            ("Low Stock", "/modules/low-stock"),
            ("Usage History", "/modules/usage-history"),
            ("Archived Inventory", "/modules/archived-inventory"),
            ("Inventory Value", "/modules/inventory-value"),
        ],
    ),
    (
        "Imports",
        [
            ("Import Inventory", "/modules/import-inventory"),
            ("Import History", "/modules/import-history"),
            ("Validation Results", "/modules/validation-results"),
        ],
    ),
    (
        "Integrations",
        [
            ("Maeve", "/modules/maeve"),
            ("Printers", "/modules/printers"),
            ("RFID / NFC / Barcode", "/modules/rfid-nfc-barcode"),
            ("External Services", "/modules/external-services"),
        ],
    ),
    (
        "Settings",
        [
            ("Categories", "/modules/categories"),
            ("Item Types", "/modules/item-types"),
            ("Attributes", "/modules/attributes"),
            ("Units", "/modules/units"),
            ("Tracking Policies", "/modules/tracking-policies"),
            ("Locations", "/modules/location-settings"),
            ("Identification Rules", "/modules/identification-rules"),
            ("Application Settings", "/modules/application-settings"),
        ],
    ),
]

MODULES = {
    path.removeprefix("/modules/"): label
    for _, links in NAVIGATION
    for label, path in links
    if path.startswith("/modules/")
}

# Preserve old bookmarked placeholder routes while real modules replace their navigation links.
MODULES["project-list"] = "Project List"
MODULES["equipment-maintenance"] = "Equipment Maintenance"
