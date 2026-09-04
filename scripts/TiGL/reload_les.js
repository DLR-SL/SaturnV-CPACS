// Open via: app.openScript("reload_les.js")

app.openFile("cpacs/saturnV.xml");
app.scene.deleteAllObjects();
app.getDocument().drawComponentByUID("apolloLES");
app.openFile("f1_cads/f1.brep");
app.viewer.fitAll();
