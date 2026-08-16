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

const sources = {
  calculus:{
    macro:'tools/macros/mathprint-editor-extra-structural-navigation.macro',
    trace:'/tmp/mp-extra-structural-navigation.trace',
  },
  remaining:{
    macro:'tools/macros/mathprint-editor-remaining-structural-navigation.macro',
    trace:'/tmp/mp-remaining-structural-navigation.trace',
  },
  matrix:{
    macro:'tools/macros/mathprint-editor-matrix-navigation.macro',
    trace:'/tmp/mp-matrix-navigation.trace',
  },
  nested:{
    macro:'tools/macros/mathprint-editor-nested-fraction-left-navigation.macro',
    trace:'/tmp/mp-nested-fraction-left-navigation.trace',
  },
  mixed:{
    macro:'tools/macros/mathprint-editor-radical-fraction-navigation.macro',
    trace:'/tmp/mp-radical-fraction-navigation.trace',
  },
};
const specs = [
  {
    source:'calculus',name:'nderiv_left',
    prefix:'/tmp/mp-nderiv-left-walk',direction:'left',
    states:[
      'root_after','value_end','value_start','body_end','body_start',
      'variable','root_before','root_before_endpoint',
    ],
  },
  {
    source:'calculus',name:'nderiv_right',
    prefix:'/tmp/mp-nderiv-right-walk',direction:'right',
    states:[
      'root_before','variable','body_start','body_end','value_start',
      'value_end','root_after','root_after_endpoint',
    ],
  },
  {
    source:'calculus',name:'logbase_left',
    prefix:'/tmp/mp-logbase-left-walk',direction:'left',
    states:[
      'root_after','argument_end','argument_start','base_end','base_start',
      'root_before','root_before_endpoint',
    ],
  },
  {
    source:'calculus',name:'logbase_right',
    prefix:'/tmp/mp-logbase-right-walk',direction:'right',
    states:[
      'root_before','base_start','base_end','argument_start','argument_end',
      'root_after','root_after_endpoint',
    ],
  },
  {
    source:'remaining',name:'radical_left',
    prefix:'/tmp/mp-radical-left-walk',direction:'left',
    states:[
      'root_after','radicand_end','radicand_start','root_before',
      'root_before_endpoint',
    ],
  },
  {
    source:'remaining',name:'radical_right',
    prefix:'/tmp/mp-radical-right-walk',direction:'right',
    states:[
      'root_before','radicand_start','radicand_end','root_after',
      'root_after_endpoint',
    ],
  },
  {
    source:'remaining',name:'nthroot_left',
    prefix:'/tmp/mp-nthroot-left-walk',direction:'left',
    states:[
      'root_after','radicand_end','radicand_start','index_end','index_start',
      'root_before','root_before_endpoint',
    ],
  },
  {
    source:'remaining',name:'nthroot_right',
    prefix:'/tmp/mp-nthroot-right-walk',direction:'right',
    states:[
      'root_before','index_start','index_end','radicand_start','radicand_end',
      'root_after','root_after_endpoint',
    ],
  },
  {
    source:'remaining',name:'power_left',
    prefix:'/tmp/mp-power-left-walk',direction:'left',
    states:[
      'root_after','exponent_end','exponent_start','marker_before',
      'base_before','base_before_endpoint',
    ],
  },
  {
    source:'remaining',name:'power_right',
    prefix:'/tmp/mp-power-right-walk',direction:'right',
    states:[
      'base_before','marker_before','exponent_start','exponent_end',
      'root_after','root_after_endpoint',
    ],
  },
  {
    source:'remaining',name:'absolute_left',
    prefix:'/tmp/mp-absolute-left-walk',direction:'left',
    states:[
      'root_after','body_end','body_start','root_before',
      'root_before_endpoint',
    ],
  },
  {
    source:'remaining',name:'absolute_right',
    prefix:'/tmp/mp-absolute-right-walk',direction:'right',
    states:[
      'root_before','body_start','body_end','root_after',
      'root_after_endpoint',
    ],
  },
  {
    source:'remaining',name:'epower_left',
    prefix:'/tmp/mp-epower-left-walk',direction:'left',
    states:[
      'root_after','exponent_end','exponent_start','root_before',
      'root_before_endpoint',
    ],
  },
  {
    source:'remaining',name:'epower_right',
    prefix:'/tmp/mp-epower-right-walk',direction:'right',
    states:[
      'root_before','exponent_start','exponent_end','root_after',
      'root_after_endpoint',
    ],
  },
  {
    source:'remaining',name:'tenpower_left',
    prefix:'/tmp/mp-tenpower-left-walk',direction:'left',
    states:[
      'root_after','exponent_end','exponent_start','root_before',
      'root_before_endpoint',
    ],
  },
  {
    source:'remaining',name:'tenpower_right',
    prefix:'/tmp/mp-tenpower-right-walk',direction:'right',
    states:[
      'root_before','exponent_start','exponent_end','root_after',
      'root_after_endpoint',
    ],
  },
  {
    source:'matrix',name:'matrix_tokens_left',
    prefix:'/tmp/mp-matrix-left-walk',direction:'left',
    states:[
      'offset_5','offset_4','offset_3','offset_2','offset_1','offset_0',
      'offset_0_endpoint',
    ],
  },
  {
    source:'matrix',name:'matrix_tokens_right',
    prefix:'/tmp/mp-matrix-right-walk',direction:'right',
    states:[
      'offset_0','offset_1','offset_2','offset_3','offset_4','offset_5',
      'offset_5_endpoint',
    ],
  },
  {
    source:'nested',name:'nested_fraction_left',
    prefix:'/tmp/mp-nested-fraction-left-walk',direction:'left',
    states:[
      'root_after','outer_denominator_start','outer_numerator_end',
      'outer_numerator_after_inner','inner_denominator_end',
      'inner_denominator_start','inner_numerator_end','inner_numerator_start',
      'outer_numerator_start','root_before','root_before_endpoint',
    ],
  },
  {
    source:'mixed',name:'radical_fraction_left',
    prefix:'/tmp/mp-radical-fraction-left-walk',direction:'left',
    states:[
      'root_after','radicand_after_fraction','inner_denominator_end',
      'inner_denominator_start','inner_numerator_end','inner_numerator_start',
      'radicand_before_fraction','root_before','root_before_endpoint',
    ],
  },
  {
    source:'mixed',name:'radical_fraction_right',
    prefix:'/tmp/mp-radical-fraction-right-walk',direction:'right',
    states:[
      'root_before','radicand_before_fraction','inner_numerator_start',
      'inner_numerator_end','inner_denominator_start','inner_denominator_end',
      'radicand_after_fraction','root_after','root_after_endpoint',
    ],
  },
];

const digest = bytes =>
  crypto.createHash('sha256').update(bytes).digest('hex');

const captures = {};
const transitions = [];
for (const spec of specs) {
  const source = sources[spec.source];
  if (!source) throw new Error(`${spec.name}: unknown capture source`);
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
    macro:source.macro,
    macro_sha256:digest(fs.readFileSync(path.join(root,source.macro))),
    trace_sha256:digest(fs.readFileSync(source.trace)),states,
  };
}

process.stdout.write(`${JSON.stringify({schema:5,captures,transitions},null,2)}\n`);
