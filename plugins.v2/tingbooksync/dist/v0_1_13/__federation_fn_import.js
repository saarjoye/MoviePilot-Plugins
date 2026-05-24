const moduleMap = {};
const moduleCache = Object.create(null);

async function importShared(name, shareScope = "default") {
  return moduleCache[name] || (await getSharedFromRuntime(name, shareScope));
}

async function getSharedFromRuntime(name, shareScope) {
  let module = null;
  if (globalThis?.__federation_shared__?.[shareScope]?.[name]) {
    const versionObj = globalThis.__federation_shared__[shareScope][name];
    const versionKey = Object.keys(versionObj)[0];
    if (versionKey) {
      const versionValue = versionObj[versionKey];
      module = await (await versionValue.get())();
    }
  }
  if (!module) {
    throw new Error(`shared module not found: ${name}`);
  }
  return flattenModule(module, name);
}

function flattenModule(module, name) {
  if (typeof module.default === "function") {
    Object.keys(module).forEach((key) => {
      if (key !== "default") module.default[key] = module[key];
    });
    moduleCache[name] = module.default;
    return module.default;
  }
  if (module.default) module = Object.assign({}, module.default, module);
  moduleCache[name] = module;
  return module;
}

export { importShared };
