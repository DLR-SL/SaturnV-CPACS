import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'

const container = document.getElementById('app')

const scene = new THREE.Scene()
scene.background = new THREE.Color(0x1a2029)

const camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 5000)
camera.position.set(60, 40, 60)

// logarithmicDepthBuffer: the tank domes sit a few millimetres inside the
// fuselage shells. With a conventional depth buffer and a near/far range that
// has to cover a 110 m launcher, the precision left at that distance is not
// enough to separate the two surfaces, and which one wins flips as the camera
// moves — the flickering domes. Logarithmic depth spends its precision far
// more evenly along the view ray and removes the effect.
const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true })
renderer.setSize(window.innerWidth, window.innerHeight)
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
renderer.toneMapping = THREE.ACESFilmicToneMapping
renderer.toneMappingExposure = 1.6
renderer.shadowMap.enabled = true
renderer.shadowMap.type = THREE.PCFSoftShadowMap
container.appendChild(renderer.domElement)

const pmrem = new THREE.PMREMGenerator(renderer)
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture

const controls = new OrbitControls(camera, renderer.domElement)
controls.enableDamping = true
controls.dampingFactor = 0.06
controls.maxPolarAngle = Math.PI * 0.52
controls.autoRotateSpeed = 0.6

// modelRoot's -90 degree x-rotation puts the launcher axis on world y, and
// OrbitControls orbits the camera around the up vector through its target — so
// an auto-orbit reads as a slow spin of the rocket about its own long axis,
// while grid, shadow and lighting stay put.
const spinToggle = document.getElementById('spin-toggle')
spinToggle.addEventListener('click', () => {
  controls.autoRotate = !controls.autoRotate
  spinToggle.setAttribute('aria-pressed', String(controls.autoRotate))
})

const keyLight = new THREE.DirectionalLight(0xffffff, 2.2)
keyLight.position.set(60, 90, 40)
keyLight.castShadow = true
scene.add(keyLight)

const rimLight = new THREE.DirectionalLight(0x88aaff, 0.8)
rimLight.position.set(-50, 30, -60)
scene.add(rimLight)

const fillLight = new THREE.HemisphereLight(0xbdd4f0, 0x2a3038, 1.4)
scene.add(fillLight)

const loader = new STLLoader()
const base = import.meta.env.BASE_URL
const modelRoot = new THREE.Group()
// CPACS puts the launcher axis on z, three.js uses y as up.
modelRoot.rotation.x = -Math.PI / 2
scene.add(modelRoot)

const components = new Map()
// Category -> transparency in [0, 1]. This is the single source of truth for
// how see-through a group is; entry.opacity only seeds the initial value.
const groupTransparency = new Map()
let explodeFactor = 0.0

const MATERIAL_PRESETS = {
  fuselage: { color: 0xd8dce2, metalness: 0.55, roughness: 0.38 },
  fuelTank: { color: 0x3d7ab8, metalness: 0.25, roughness: 0.5 },
  genericSystem: { color: 0x9aa3ad, metalness: 0.8, roughness: 0.28 },
  wing: { color: 0xd8dce2, metalness: 0.55, roughness: 0.38 },
  enginePylon: { color: 0xb9c0c9, metalness: 0.6, roughness: 0.35 },
  baffle: { color: 0xe0913c, metalness: 0.3, roughness: 0.55 }
}

// Categories exported as open surfaces rather than closed solids. They get no
// shadow casting: a zero-thickness sheet inside a translucent tank throws a
// hard shadow onto the ground that reads as a modelling error.
const OPEN_SURFACE_CATEGORIES = new Set(['baffle'])

const presetFor = (category) => MATERIAL_PRESETS[category] ?? MATERIAL_PRESETS.fuselage

function applyOpacity(mesh, opacity) {
  mesh.material.transparent = opacity < 1.0
  mesh.material.opacity = opacity
  // Keeping depth writes until the surface is clearly see-through limits the
  // sorting artefacts you get with 13 nested fuselage shells.
  mesh.material.depthWrite = opacity > 0.75
}

function updateComponent(uid) {
  const comp = components.get(uid)
  if (!comp) return
  comp.mesh.visible = comp.visible
  const transparency = groupTransparency.get(comp.entry.category) ?? 0
  applyOpacity(comp.mesh, Math.max(1 - transparency, 0.05))
}

function setGroupTransparency(category, transparency) {
  groupTransparency.set(category, transparency)
  for (const [uid, comp] of components) {
    if (comp.entry.category === category) updateComponent(uid)
  }
}

// Shifts every component along the launcher axis, proportional to its distance
// from the mid-point, so the stages pull apart symmetrically.
function updateExplode() {
  for (const comp of components.values()) {
    comp.mesh.position.z = (comp.axialOffset ?? 0) * explodeFactor
  }
}

async function loadComponent(entry) {
  const geometry = await loader.loadAsync(`${base}models/${entry.file}`)
  // No computeVertexNormals(): STLLoader already provides the normal attribute,
  // and STL geometry is never indexed, so the call would only recompute the
  // very same face normals.
  geometry.computeBoundingBox()
  // Without this three.js derives the culling sphere lazily from the bounding
  // box, which overestimates it for the long, thin stage shells and can cull a
  // component that is still partly on screen.
  geometry.computeBoundingSphere()

  const preset = presetFor(entry.category)
  const material = new THREE.MeshStandardMaterial({
    color: entry.color ? new THREE.Color(entry.color) : new THREE.Color(preset.color),
    metalness: preset.metalness,
    roughness: preset.roughness,
    envMapIntensity: 1.5,
    side: THREE.DoubleSide
  })

  const isOpenSurface = OPEN_SURFACE_CATEGORIES.has(entry.category)

  const mesh = new THREE.Mesh(geometry, material)
  mesh.castShadow = !isOpenSurface
  mesh.receiveShadow = !isOpenSurface
  // Baffles sit inside the tank shell. Drawing them before every translucent
  // hull keeps them from being culled away by the tank's own depth pass.
  mesh.renderOrder = isOpenSurface ? -1 : 0
  modelRoot.add(mesh)

  const center = new THREE.Vector3()
  geometry.boundingBox.getCenter(center)

  if (!groupTransparency.has(entry.category)) {
    groupTransparency.set(entry.category, 1 - (entry.opacity ?? 1))
  }

  components.set(entry.uid, {
    mesh,
    entry,
    visible: true,
    axialCenter: center.z
  })
  updateComponent(entry.uid)
}

async function loadAllModels() {
  const response = await fetch(`${base}models/models.json`)
  if (!response.ok) {
    throw new Error(`Failed to load models.json: ${response.status}`)
  }
  const entries = await response.json()
  await Promise.all(entries.map(loadComponent))
  return entries
}

function setupGround(modelBox) {
  const size = modelBox.getSize(new THREE.Vector3())
  const maxDim = Math.max(size.x, size.y, size.z)
  // Fog and ground scale with the OVERALL LENGTH, not the diameter. Otherwise
  // the whole model sits behind fog.far and disappears into the haze.
  const radius = maxDim * 0.9

  const shadowPlane = new THREE.Mesh(
    new THREE.PlaneGeometry(radius * 2, radius * 2),
    new THREE.ShadowMaterial({ opacity: 0.45 })
  )
  shadowPlane.rotation.x = -Math.PI / 2
  shadowPlane.position.y = modelBox.min.y
  shadowPlane.receiveShadow = true
  scene.add(shadowPlane)

  const grid = new THREE.GridHelper(radius * 2, 60, 0x5a6675, 0x333d49)
  grid.position.y = modelBox.min.y
  grid.material.transparent = true
  grid.material.opacity = 0.5
  scene.add(grid)

  scene.fog = new THREE.Fog(0x1a2029, maxDim * 1.6, maxDim * 4.5)

  // Fit the shadow camera to the model, otherwise the shadow of a 110 m
  // launcher falls outside the frustum entirely.
  const h = size.y
  const cam = keyLight.shadow.camera
  cam.left = -h * 0.35
  cam.right = h * 0.35
  cam.top = h * 0.7
  cam.bottom = -h * 0.2
  cam.near = 1
  cam.far = h * 4
  keyLight.shadow.mapSize.set(2048, 2048)
  keyLight.position.set(h * 0.5, h * 0.9, h * 0.4)
  cam.updateProjectionMatrix()
}

function fitCameraToObject(box, offset = 1.4) {
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())
  const maxDim = Math.max(size.x, size.y, size.z)
  const fov = camera.fov * (Math.PI / 180)
  const dist = Math.abs(maxDim / 2 / Math.tan(fov / 2)) * offset

  camera.position.set(center.x + dist * 0.55, center.y + size.y * 0.15, center.z + dist * 0.55)
  // A tight far plane costs nothing here (the model plus its ground plane is
  // all there is) and keeps the depth range small even if the logarithmic
  // buffer is unavailable on a given GPU.
  camera.near = Math.max(maxDim / 200, 0.1)
  camera.far = maxDim * 6
  camera.updateProjectionMatrix()
  controls.target.copy(center)
  controls.minDistance = maxDim * 0.15
  controls.maxDistance = maxDim * 4
  controls.update()
}

function buildGroupHeader(group, category, count) {
  const heading = document.createElement('div')
  heading.className = 'group-heading'

  const name = document.createElement('span')
  name.className = 'name'
  name.textContent = `${category} (${count})`

  const toggleAll = document.createElement('button')
  toggleAll.className = 'toggle-all'
  toggleAll.textContent = 'all'
  toggleAll.addEventListener('click', () => {
    const boxes = group.querySelectorAll('input[type=checkbox]')
    const anyOff = [...boxes].some((b) => !b.checked)
    boxes.forEach((b) => {
      b.checked = anyOff
      b.dispatchEvent(new Event('change'))
    })
  })

  heading.append(name, toggleAll)

  // Reads as opacity: right is fully opaque, left is maximum transparency.
  const slider = document.createElement('input')
  slider.type = 'range'
  slider.className = 'group-opacity'
  slider.min = '0'
  slider.max = '100'
  slider.value = String(Math.round((1 - (groupTransparency.get(category) ?? 0)) * 100))
  slider.title = `Opacity — ${category}`
  slider.setAttribute('aria-label', `Opacity for ${category}`)
  slider.addEventListener('input', (e) => {
    setGroupTransparency(category, 1 - Number(e.target.value) / 100)
  })

  return [heading, slider]
}

function buildPanel(entries) {
  const panel = document.getElementById('panel')
  panel.innerHTML = ''

  const categories = {}
  for (const entry of entries) {
    categories[entry.category] ??= []
    categories[entry.category].push(entry)
  }

  for (const [category, items] of Object.entries(categories)) {
    const group = document.createElement('div')
    group.className = 'group'
    group.append(...buildGroupHeader(group, category, items.length))

    for (const entry of items) {
      const row = document.createElement('label')
      row.className = 'row'

      const checkbox = document.createElement('input')
      checkbox.type = 'checkbox'
      checkbox.checked = true
      checkbox.addEventListener('change', () => {
        const comp = components.get(entry.uid)
        if (!comp) return
        comp.visible = checkbox.checked
        updateComponent(entry.uid)
      })

      const swatch = document.createElement('span')
      swatch.className = 'swatch'
      const preset = presetFor(entry.category)
      swatch.style.background = entry.color ?? `#${preset.color.toString(16).padStart(6, '0')}`

      const label = document.createElement('span')
      label.className = 'label'
      label.textContent = entry.uid

      row.append(checkbox, swatch, label)
      group.appendChild(row)
    }

    panel.appendChild(group)
  }

  document.getElementById('explode-slider').addEventListener('input', (e) => {
    explodeFactor = Number(e.target.value) / 100
    updateExplode()
  })
}

const entries = await loadAllModels()
buildPanel(entries)
modelRoot.updateMatrixWorld(true)

const modelBox = new THREE.Box3().setFromObject(modelRoot)
setupGround(modelBox)
fitCameraToObject(modelBox)

// Axial offsets for the exploded view, relative to the mid-point of the
// overall length.
{
  let minZ = Infinity
  let maxZ = -Infinity
  for (const comp of components.values()) {
    minZ = Math.min(minZ, comp.axialCenter)
    maxZ = Math.max(maxZ, comp.axialCenter)
  }
  const midZ = (minZ + maxZ) / 2
  for (const comp of components.values()) {
    comp.axialOffset = (comp.axialCenter - midZ) * 0.6
  }
  // Inner structure inherits the offset of the component it sits in, otherwise
  // a baffle slides out through the tank dome as the stages pull apart.
  for (const comp of components.values()) {
    const parent = comp.entry.parent ? components.get(comp.entry.parent) : undefined
    if (parent) comp.axialOffset = parent.axialOffset
  }
}

document.getElementById('loading')?.remove()

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight
  camera.updateProjectionMatrix()
  renderer.setSize(window.innerWidth, window.innerHeight)
})

function animate() {
  requestAnimationFrame(animate)
  controls.update()
  renderer.render(scene, camera)
}
animate()
