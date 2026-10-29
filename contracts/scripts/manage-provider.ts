import { ethers, network } from "hardhat";

async function main() {
  if (network.name !== "localhost") {
    throw new Error("Provider access management is restricted to the explicitly selected localhost network.");
  }
  const ledgerAddress = process.env.RIGHTS_LEDGER_ADDRESS;
  const providerAddress = process.env.DATASET_PROVIDER_ADDRESS;
  const action = process.env.PROVIDER_ACTION;
  if (!ledgerAddress || !providerAddress || !["authorize", "revoke"].includes(action ?? "")) {
    throw new Error("Set RIGHTS_LEDGER_ADDRESS, DATASET_PROVIDER_ADDRESS, and PROVIDER_ACTION=authorize|revoke.");
  }

  const ledgerCode = await ethers.provider.getCode(ledgerAddress);
  if (ledgerCode === "0x") throw new Error("No RightsLedger contract is deployed at RIGHTS_LEDGER_ADDRESS.");
  const provider = ethers.getAddress(providerAddress);
  const [admin] = await ethers.getSigners();
  const ledger = await ethers.getContractAt("RightsLedger", ledgerAddress, admin);
  const tx = action === "authorize"
    ? await ledger.authorizeProvider(provider)
    : await ledger.revokeProvider(provider);
  const receipt = await tx.wait();
  const authorized = await ledger.authorizedProviders(provider);
  const expected = action === "authorize";
  if (authorized !== expected) throw new Error("Provider authorization readback did not match the requested action.");
  process.stdout.write(JSON.stringify({
    action,
    provider,
    admin: admin.address,
    transactionHash: receipt?.hash,
    authorizationReadback: authorized,
    status: "confirmed",
  }, null, 2) + "\n");
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : "Provider access update failed"}\n`);
  process.exitCode = 1;
});
