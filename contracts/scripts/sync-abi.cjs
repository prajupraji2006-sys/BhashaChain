const fs = require('node:fs');
const path = require('node:path');

const contractRoot = path.resolve(__dirname, '..');
const projectRoot = path.resolve(contractRoot, '..');
const artifactPath = path.join(contractRoot, 'artifacts', 'contracts', 'RightsLedger.sol', 'RightsLedger.json');
const outputPath = path.join(projectRoot, 'backend', 'data', 'rights_ledger_abi.json');
const abi = JSON.parse(fs.readFileSync(artifactPath, 'utf8')).abi;
fs.writeFileSync(outputPath, `${JSON.stringify(abi, null, 2)}\n`, 'utf8');
process.stdout.write(`Updated backend ABI: ${path.relative(projectRoot, outputPath)}\n`);
