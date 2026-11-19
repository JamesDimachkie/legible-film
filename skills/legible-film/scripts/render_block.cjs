'use strict';
/*
 * Outbound network block for an engine render that project.py add-version --render runs.
 *
 * Loaded into every Node process of the render with NODE_OPTIONS=--require. It refuses every TCP connection that
 * leaves the loopback interface, and it starts every Chromium the engine launches with --proxy-server set to a local
 * sink that records each request and refuses it (Chromium sends loopback requests direct, so the engine's own page
 * server keeps working) plus a host-resolver rule that resolves no other name. Each Node process, each browser it
 * launched with the block and each refused connection is one JSON line in LF_BLOCK_LOG, so the caller can show the
 * block engaged and see anything the render tried to reach.
 *
 * It cannot see a program that is not Node and not a browser Node launched; those get only the proxy environment
 * variables, which a program may ignore. Exit codes and output are the engine's own.
 */
const fs = require('fs');
const net = require('net');
const path = require('path');
const {createHash} = require('crypto');
const childProcess = require('child_process');
const {syncBuiltinESMExports} = require('module');

const SINK = process.env.LF_BLOCK_PROXY || '';
const LOG = process.env.LF_BLOCK_LOG || '';

function log(row) {
  if (!LOG) return;
  try { fs.appendFileSync(LOG, JSON.stringify({pid: process.pid, ...row}) + '\n'); } catch (_) { /* the log is best effort */ }
}

(function verifyCueConstantsSync() {
  const cuesFile = process.env.LF_CUES_FILE || '';
  const cueGen = require(path.join(__dirname, 'cue_gen.cjs'));
  // LF_CUES_GEN may name several modules as a JSON list (or a single path): add-version --render gives every module it staged
  const given = cueGen.parseCuesGenEnv(process.env.LF_CUES_GEN);
  let genFile = given[0] || '';
  if (!genFile && cuesFile) {
    const dir = path.dirname(cuesFile);
    for (const cand of [path.join(dir, 'times.gen.js'), path.join(dir, 'times.gen.ts')]) {
      if (fs.existsSync(cand)) { genFile = cand; break; }
    }
  }
  if (!genFile && process.env.LF_PAGE_DIR) {
    for (const cand of [path.join(process.env.LF_PAGE_DIR, 'times.gen.js'), path.join(process.env.LF_PAGE_DIR, 'times.gen.ts')]) {
      if (fs.existsSync(cand)) { genFile = cand; break; }
    }
  }
  if (!genFile) return;
  const resolvedCues = cuesFile || path.join(path.dirname(genFile), 'cues.json');
  for (const gen of given.length ? given : [genFile]) {
    const fail = (detail) => {
      log({event: 'cues_gen_mismatch', gen, cues: resolvedCues, detail});
      process.stderr.write(`times.gen mismatch: ${detail}\n`);
      process.exit(2);
    };
    if (!fs.existsSync(resolvedCues)) fail(`missing cues.json at ${resolvedCues}`);
    if (!fs.existsSync(gen)) fail(`missing generated constants file at ${gen}`);
    try {
      // cue_list.py's rules, shared with film_capture.mjs: this preload had compared only the times and frames of the
      // cues still listed, so a removed cue, a CUES_SHA256 of 64 zeros or a shortened silence started the render
      const problems = require(path.join(__dirname, 'cue_gen.cjs')).verifyGenerated(resolvedCues, gen);
      if (problems.length) fail(problems.slice(0, 3).join('; ') + '; rerun cue_list.py codegen');
    } catch (err) {
      fail(err && err.message ? err.message : String(err));
    }
  }
})();

function loopback(host) {
  if (host == null || host === '') return true;
  const h = String(host).replace(/^\[|\]$/g, '').toLowerCase();
  return h === 'localhost' || h.endsWith('.localhost') || h === '::1' || h === '0:0:0:0:0:0:0:1' ||
    /^127\.\d+\.\d+\.\d+$/.test(h) || h === '::ffff:127.0.0.1';
}

function target(args) {
  let first = args[0];
  if (Array.isArray(first)) first = first[0];
  if (first && typeof first === 'object') return {path: first.path, host: first.host, port: first.port};
  if (typeof first === 'number' || (typeof first === 'string' && /^\d+$/.test(first)))
    return {port: Number(first), host: typeof args[1] === 'string' ? args[1] : 'localhost'};
  if (typeof first === 'string') return {path: first};
  return {};
}

const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const t = target(args);
  if (!t.path && !loopback(t.host)) {
    log({event: 'refused', host: String(t.host), port: t.port == null ? null : Number(t.port)});
    const error = Object.assign(new Error(`network blocked during the render: ${t.host}:${t.port}`), {code: 'ECONNREFUSED'});
    process.nextTick(() => this.destroy(error));
    return this;
  }
  return connect.apply(this, args);
};

const BROWSER = /chrom(e|ium)|headless[-_ ]?shell|msedge|brave/i;
function blockArgs() {
  return [`--proxy-server=${SINK}`, '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1',
          '--force-webrtc-ip-handling-policy=disable_non_proxied_udp', '--disable-quic'];
}
function isBrowser(file, args) {
  return BROWSER.test(path.basename(String(file || ''))) &&
    (args || []).some(a => typeof a === 'string' && (a.startsWith('--remote-debugging') || a.startsWith('--headless')));
}
const spawn = childProcess.spawn;
childProcess.spawn = function (file, args, options) {
  if (Array.isArray(args) && isBrowser(file, args) && SINK) {
    log({event: 'browser', exe: path.basename(String(file)), proxy: SINK});
    args = [...args, ...blockArgs()];
  }
  return spawn.call(this, file, args, options);
};
syncBuiltinESMExports();
log({event: 'node', script: process.argv[1] ? path.basename(process.argv[1]) : null});
