# Maeve Product Architecture

## Architecture goal

Maeve is a workshop-first operating system and trusted builder companion. The Raspberry Pi is the primary design target for the base unit. Maeve Core stays focused on common workshop needs while optional software and hardware modules adapt it to different builders and crafts.

## Maeve Core

The base system includes:

- Printer management
- Inventory management
- Active-project tracking
- Best-next-move guidance
- A customizable Focus Dashboard
- Voice access
- Side-menu or one-touch navigation
- Local settings and personalization

Core information must use real data or a clearly marked unavailable, unknown, or estimated state.

## Default Focus Dashboard

The default home screen contains four primary areas:

1. Printer Status
2. Inventory
3. Active Projects
4. Maeve's Recommendation

The home screen displays only information that is immediately useful to the builder. Everything else remains one touch or one voice command away. Users can pin, remove, resize, or reorder supported cards without modifying source code.

Weather is not a required base card. Work-specific information such as Paint Truck Operations appears only when its module is enabled or pinned.

## Modules

### Software module

An installable or enabled feature, screen, data connector, workflow, or dashboard-card provider. Examples include Paint Truck Operations, Weather, Calendar, Finance, Woodworking, Leather Shop, CNC, Laser, Farm Management, and community-developed modules.

Paint Truck Operations is primarily a software module and is not part of the default workshop dashboard.

### Hardware module

A physical expansion device with its supporting software, such as a sensor, camera, controller, air-quality monitor, or external interface.

Hardware integrations must fail safely and must not prevent Maeve Core from starting when a module is absent or unavailable.

## Startup experience

Startup is personalized to the builder and may include:

- Selected artwork
- Workshop name
- Greeting
- Motto
- Color theme
- Optional voice greeting
- Subtle boot progress

THS branding is optional outside official THS installations. Cowboy's personal unit may use a professionally presented Maeve character scene in the THS print room with black-and-orange workshop styling.

## Core versus personal and work modules

Maeve Core contains the capabilities common to a workshop companion. Personal, seasonal, business-specific, and employer-related workflows remain optional modules. A user may surface an enabled module on the Focus Dashboard without making it part of every installation.

## Design constraints

- Target a clean, touch-friendly seven-inch Raspberry Pi kiosk display.
- Keep core operation useful when optional services are unavailable.
- Prefer local-first storage and processing where practical.
- Keep software and hardware module boundaries documented.
- Do not force THS branding.
- Do not present missing or estimated data as confirmed fact.
- Preserve the builder's control over layout, modules, voice, and notifications.

## Meeting 005 acceptance record

- [x] Workshop-first core defined
- [x] Customizable Focus Dashboard defined
- [x] Optional module system defined
- [x] Software and hardware modules distinguished
- [x] THS branding made optional
- [x] Core, personal, and work modules separated
- [x] Raspberry Pi compatibility recorded as a design target
