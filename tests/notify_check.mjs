// Runs static/js/notify.js against a minimal stand-in for the browser and prints what happened as JSON
// (used by test_notify.py). Usage: node notify_check.mjs <path to notify.js> <hidden: 0|1> <permission>
import { pathToFileURL } from 'node:url';

const [notifyPath, hidden, permission] = process.argv.slice(2);
const listeners = {};
const element = (tag) => ({
    tag, children: [], attributes: {}, className: '', textContent: '',
    setAttribute(k, v) { this.attributes[k] = v; },
    appendChild(child) { this.children.push(child); child.parent = this; },
    addEventListener() {},
    remove() { this.parent.children = this.parent.children.filter((c) => c !== this); },
});
const body = element('body');
globalThis.document = {
    title: 'BASIC OS', hidden: hidden === '1', body,
    getElementById: (id) => body.children.find((c) => c.id === id) || null,
    createElement: element,
    addEventListener: (type, fn) => { listeners[type] = fn; },
};
const shown = [];
globalThis.window = { focus() {} };
class FakeNotification {
    static permission = permission;
    static requestPermission() { FakeNotification.asked = true; return Promise.resolve(permission); }
    constructor(title, options) { shown.push({ title, body: options.body }); }
    addEventListener() {}
}
globalThis.window.Notification = FakeNotification;
globalThis.Notification = FakeNotification;
globalThis.setTimeout = () => 0;

const { longJob } = await import(pathToFileURL(notifyPath).href);
const ok = await longJob('The hub generator', Promise.resolve({ text: 'done' }));
await longJob('The game plan', Promise.resolve({ error: 'Ollama is not running' }));
let rethrown = false;
try { await longJob('The podcast recording', Promise.reject(new Error('network down'))); } catch { rethrown = true; }
const toasts = body.children[0].children.map((t) => ({ text: t.textContent, error: t.className.includes('toast--error') }));
console.log(JSON.stringify({ ok, toasts, shown, title: document.title, asked: Boolean(FakeNotification.asked), rethrown }));
