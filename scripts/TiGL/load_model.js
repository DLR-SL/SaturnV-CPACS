// Open via: app.openScript("load_model.js")
//
// Draws the complete Saturn V model:
//   structure (fuselages / wings) -> drawConfiguration()
//   fuelTanks (vessels)           -> drawComponentByUID(<fuelTank uID>)
//   systems   (genericSystems)    -> drawSystems()
//
// drawConfiguration() only covers TIGL_COMPONENT_FUSELAGE/WING/ROTOR/PYLON/
// NACELLE/EXTERNAL_OBJECT. Tanks (TIGL_COMPONENT_TANK) and genericSystems are
// not included and have to be drawn separately.

var CPACS_FILE = "saturnV.xml";

var SHOW_STRUCTURE = true;
var SHOW_TANKS     = true;
var SHOW_SYSTEMS   = true;
var CLEAR_SCENE    = true;

// Shorten this list to draw only selected tanks. A fuelTank uID automatically
// draws all vessels belonging to it.
var FUEL_TANKS = [
    "s-ic_fuelTank",
    "s-ic_oxidizer",
    "s-ii_lh2",
    "s-ii_oxidizer",
    "s-ivb_lh2",
    "s-ivb_oxidizer"
];

// Alternative to drawSystems(): set USE_DRAW_SYSTEMS = false and adjust the
// list to draw individual genericSystems.
var USE_DRAW_SYSTEMS = true;
var GENERIC_SYSTEMS = [
    "apolloLES",
    "engines",
    "s-ic_fuelFeed",
    "s-ic_loxFeed"
];

function draw(uid) {
    try {
        app.getDocument().drawComponentByUID(uid);
    }
    catch (e) {
        // uID not (yet) present in the model -> skip instead of aborting
    }
}

app.openFile(CPACS_FILE);

if (CLEAR_SCENE) {
    app.scene.deleteAllObjects();
}

if (SHOW_STRUCTURE) {
    app.getDocument().drawConfiguration(false);
}

if (SHOW_TANKS) {
    for (var i = 0; i < FUEL_TANKS.length; i++) {
        draw(FUEL_TANKS[i]);
    }
}

if (SHOW_SYSTEMS) {
    if (USE_DRAW_SYSTEMS) {
        app.getDocument().drawSystems();
    }
    else {
        for (var j = 0; j < GENERIC_SYSTEMS.length; j++) {
            draw(GENERIC_SYSTEMS[j]);
        }
    }
}

app.viewer.fitAll();
