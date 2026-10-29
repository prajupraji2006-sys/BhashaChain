import { buildModule } from "@nomicfoundation/hardhat-ignition/modules";
// V2 intentionally gets a fresh Ignition deployment record for the provider ACL.
export default buildModule("RightsLedgerModuleV2", (m) => ({ ledger: m.contract("RightsLedger") }));
