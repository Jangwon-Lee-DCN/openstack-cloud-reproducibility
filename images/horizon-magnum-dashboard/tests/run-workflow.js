'use strict';
// Execute the real patched workflow, with synthetic API boundaries only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const [sourcePath, scenario] = process.argv.slice(2);
let source = fs.readFileSync(sourcePath, 'utf8');
if (scenario === 'missing-binding') {
  const declaration = /      var availabilityZoneTitleMap = \[\{value: '',\n        name: gettext\('Choose an Availability Zone'\)\}\];\n/;
  assert(declaration.test(source), 'baseline internal AZ map declaration absent');
  source = source.replace(declaration, '');
}
let factory;
const angular = {
  module() { return {factory(name, value) {factory = value;}}; },
  forEach(items, callback) {items.forEach(callback);}
};
vm.runInNewContext(source, {angular}, {filename: sourcePath});
assert.equal(typeof factory, 'function');
const response = data => Promise.resolve({data});
const zones = scenario === 'zero' ? [] : scenario === 'one' ?
  [{zoneName: 'az-test-b'}] : [{zoneName: 'az-test-b'}, {zoneName: 'az-test-c'}];
const api = {
  getClusterTemplates: () => response({items: [{id:'template-test',name:'template-test'}]}),
  getAddons: () => response({addons: []}),
  getIngressControllers: () => response({controllers: []}),
  getAvailabilityZones: () => scenario === 'dependency-failure' ?
    Promise.reject(new Error('synthetic AZ dependency rejected')) : response({items: zones}),
  getKeypairs: () => response({items: [{keypair: {name:'persona-test-key'}}]}),
  getNetworks: () => response({items: []}),
  getFlavors: () => response({items: [{name:'c5.large'}]})
};
const scope = {$watch() {return () => {};}, $on() {}};
const workflow = factory({all: values => Promise.all(values)}, '/fixture/', s => s, api, api, api);
const keys = [];
function visit(value) {
  if (value && typeof value === 'object') {
    if (value.key) keys.push(value.key);
    Object.values(value).forEach(visit);
  }
}
(async () => {
  try {
    const config = await workflow.init('Create Kubernetes Cluster', scope);
    assert.notEqual(scenario, 'missing-binding');
    assert.notEqual(scenario, 'dependency-failure');
    assert.equal(config.title, 'Create Kubernetes Cluster');
    assert.equal(config.model.keypair, 'persona-test-key');
    assert.equal(config.model.master_count, 1);
    assert.equal(config.model.node_count, 1);
    assert.equal(config.model.master_lb_enabled, true);
    assert.equal(config.model.availability_zone, scenario === 'one' ? 'az-test-b' : '');
    visit(config.form);
    assert(!keys.includes('availability_zone'), 'hidden AZ selector was exposed');
    assert(keys.includes('name') && keys.includes('cluster_template_id') && keys.includes('keypair'));
    console.log(JSON.stringify({passed:true, scenario, initialized:true}));
  } catch (error) {
    if (scenario === 'missing-binding') {
      assert.equal(error.name, 'ReferenceError');
      assert.match(error.message, /availabilityZoneTitleMap/);
    } else if (scenario === 'dependency-failure') {
      assert.equal(error.message, 'synthetic AZ dependency rejected');
    } else {throw error;}
    console.log(JSON.stringify({passed:true, scenario, initialized:false, rejected:true}));
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
