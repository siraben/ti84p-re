#!/usr/bin/env node
// Reduce the completed nDeriv and log-base cursor walks captured by
// mathprint-editor-extra-structural-navigation.macro. The generic reducer
// checks every translated transition against the full decoded arena; this
// wrapper combines the four walks into one committed oracle.

'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const root = path.dirname(__dirname);
const rom = require(path.join(root,'web','mathprint','rom-engine.js'));
const font = JSON.parse(fs.readFileSync(
  path.join(root,'web','mathprint','font.json')));
rom.setSettledTokenStrings(JSON.parse(fs.readFileSync(
  path.join(root,'web','mathprint','token-strings.json'))));
const capture = require(path.join(
  root,'tools','capture-mathprint-editor-navigation.js'));

const macro = 'tools/macros/mathprint-editor-extra-structural-navigation.macro';
const trace = '/tmp/mp-extra-structural-navigation.trace';
const specs = [
  {
    name:'nderiv_left',prefix:'/tmp/mp-nderiv-left-walk',direction:'left',
    states:[
      'root_after','value_end','value_start','body_end','body_start',
      'variable','root_before','root_before_endpoint',
    ],
  },
  {
    name:'nderiv_right',prefix:'/tmp/mp-nderiv-right-walk',direction:'right',
    states:[
      'root_before','variable','body_start','body_end','value_start',
      'value_end','root_after','root_after_endpoint',
    ],
  },
  {
    name:'logbase_left',prefix:'/tmp/mp-logbase-left-walk',direction:'left',
    states:[
      'root_after','argument_end','argument_start','base_end','base_start',
      'root_before','root_before_endpoint',
    ],
  },
  {
    name:'logbase_right',prefix:'/tmp/mp-logbase-right-walk',direction:'right',
    states:[
      'root_before','base_start','base_end','argument_start','argument_end',
      'root_after','root_after_endpoint',
    ],
  },
];

const digest = bytes =>
  crypto.createHash('sha256').update(bytes).digest('hex');

const captures = {};
const transitions = [];
for (const spec of specs) {
  const states = spec.states.map((name,index) =>
    capture.captureState(spec.prefix,index,name));
  const decoded = states.map(capture.decodeSparse);
  for (let index = 0; index + 1 < decoded.length; index++) {
    const moved = rom.editorMoveCursor(decoded[index],spec.direction,font);
    if (!capture.sameState(moved.state,decoded[index + 1]))
      throw new Error(
        `${spec.name}: translated transition ${index} does not match state ${index + 1}`);
    transitions.push({
      capture:spec.name,from_index:index,to_index:index + 1,
      direction:spec.direction,status:moved.mutation.status,
      routine:moved.mutation.routine,
    });
  }
  captures[spec.name] = {
    macro,macro_sha256:digest(fs.readFileSync(path.join(root,macro))),
    trace_sha256:digest(fs.readFileSync(trace)),states,
  };
}

process.stdout.write(`${JSON.stringify({schema:1,captures,transitions},null,2)}\n`);
