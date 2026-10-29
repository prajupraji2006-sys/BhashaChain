import { expect } from "chai";
import { ethers } from "hardhat";

async function deployLedger() {
  const Ledger = await ethers.getContractFactory("RightsLedger");
  const ledger = await Ledger.deploy();
  await ledger.waitForDeployment();
  return ledger;
}

function validTerms() {
  return {
    id: ethers.id("dataset"),
    hash: ethers.id("corpus"),
    purpose: ethers.id("research"),
    region: ethers.id("IN"),
  };
}

async function futureExpiry(offsetSeconds = 86400) {
  const block = await ethers.provider.getBlock("latest");
  return block!.timestamp + offsetSeconds;
}

describe("RightsLedger provider access control", function () {
  it("rejects ordinary accounts from registration and provider role grants", async function () {
    const [admin, stranger] = await ethers.getSigners();
    const ledger = await deployLedger();
    const { id, hash, purpose, region } = validTerms();
    const expiry = await futureExpiry();

    expect(await ledger.owner()).to.equal(admin.address);
    expect(await ledger.authorizedProviders(stranger.address)).to.equal(false);
    await expect(ledger.connect(stranger).authorizeProvider(stranger.address))
      .to.be.revertedWithCustomError(ledger, "NotOwner");
    await expect(ledger.connect(stranger).register(id, hash, 1, expiry, false, false, [purpose], [region]))
      .to.be.revertedWithCustomError(ledger, "ProviderNotAuthorized");
    const unregistered = await ledger.getLicence(id);
    expect(unregistered[7]).to.equal(false);
  });

  it("allows an explicitly authorized provider to register and preserves issuer update/revoke rights", async function () {
    const [admin, provider, stranger] = await ethers.getSigners();
    const ledger = await deployLedger();
    const { id, hash, purpose, region } = validTerms();
    const expiry = await futureExpiry();

    await expect(ledger.connect(admin).authorizeProvider(provider.address))
      .to.emit(ledger, "ProviderAuthorized");
    expect(await ledger.authorizedProviders(provider.address)).to.equal(true);
    await expect(ledger.connect(provider).register(id, hash, 1, expiry, true, false, [purpose], [region]))
      .to.emit(ledger, "LicenceRegistered").withArgs(id, hash, 1, provider.address);
    expect(await ledger.permits(id, purpose, region, false, false)).to.equal(true);

    await expect(ledger.connect(stranger).update(id, ethers.id("corpus-v2"), 2, expiry, false, false, [purpose], [region]))
      .to.be.revertedWithCustomError(ledger, "NotIssuer");
    await expect(ledger.connect(stranger).revoke(id))
      .to.be.revertedWithCustomError(ledger, "NotIssuer");
    await expect(ledger.connect(provider).update(id, ethers.id("corpus-v2"), 2, expiry, false, false, [purpose], [region]))
      .to.emit(ledger, "LicenceUpdated");
    await expect(ledger.connect(provider).revoke(id)).to.emit(ledger, "LicenceRevoked");
    expect(await ledger.permits(id, purpose, region, false, false)).to.equal(false);
  });

  it("lets only the owner revoke provider registration access", async function () {
    const [admin, provider, stranger] = await ethers.getSigners();
    const ledger = await deployLedger();
    const { id, hash, purpose, region } = validTerms();
    const expiry = await futureExpiry();

    await expect(ledger.connect(stranger).revokeProvider(provider.address))
      .to.be.revertedWithCustomError(ledger, "NotOwner");
    await ledger.connect(admin).authorizeProvider(provider.address);
    await ledger.connect(provider).register(id, hash, 1, expiry, false, false, [purpose], [region]);
    await expect(ledger.connect(admin).revokeProvider(provider.address)).to.emit(ledger, "ProviderAuthorizationRevoked");
    expect(await ledger.authorizedProviders(provider.address)).to.equal(false);
    await expect(ledger.connect(provider).register(ethers.id("after-revocation"), hash, 1, expiry, false, false, [purpose], [region]))
      .to.be.revertedWithCustomError(ledger, "ProviderNotAuthorized");

    // Revoking registration access does not remove the provider's authority over
    // records it previously issued.
    await expect(ledger.connect(provider).update(id, ethers.id("corpus-v2"), 2, expiry, false, false, [purpose], [region]))
      .to.emit(ledger, "LicenceUpdated");
    await expect(ledger.connect(provider).revoke(id)).to.emit(ledger, "LicenceRevoked");
  });

  it("rejects duplicate IDs and invalid registration metadata", async function () {
    const [admin, provider] = await ethers.getSigners();
    const ledger = await deployLedger();
    await ledger.connect(admin).authorizeProvider(provider.address);
    const { id, hash, purpose, region } = validTerms();
    const expiry = await futureExpiry();
    await ledger.connect(provider).register(id, hash, 1, expiry, false, false, [purpose], [region]);

    await expect(ledger.connect(provider).register(id, hash, 1, expiry, false, false, [purpose], [region]))
      .to.be.revertedWithCustomError(ledger, "AlreadyRegistered");
    await expect(ledger.connect(provider).register(ethers.ZeroHash, hash, 1, expiry, false, false, [purpose], [region]))
      .to.be.revertedWithCustomError(ledger, "InvalidInput");
    await expect(ledger.connect(provider).register(ethers.id("zero-hash"), ethers.ZeroHash, 1, expiry, false, false, [purpose], [region]))
      .to.be.revertedWithCustomError(ledger, "InvalidInput");
    await expect(ledger.connect(provider).register(ethers.id("zero-version"), hash, 0, expiry, false, false, [purpose], [region]))
      .to.be.revertedWithCustomError(ledger, "InvalidInput");
    await expect(ledger.connect(provider).register(ethers.id("expired"), hash, 1, 1, false, false, [purpose], [region]))
      .to.be.revertedWithCustomError(ledger, "InvalidInput");
  });

  it("enforces expiry and revocation in permit checks", async function () {
    const [admin, provider] = await ethers.getSigners();
    const ledger = await deployLedger();
    await ledger.connect(admin).authorizeProvider(provider.address);
    const { id, hash, purpose, region } = validTerms();
    const expiry = await futureExpiry(120);
    await ledger.connect(provider).register(id, hash, 1, expiry, false, false, [purpose], [region]);
    expect(await ledger.permits(id, purpose, region, false, false)).to.equal(true);
    await ethers.provider.send("evm_setNextBlockTimestamp", [expiry]);
    await ethers.provider.send("evm_mine", []);
    expect(await ledger.permits(id, purpose, region, false, false)).to.equal(false);

    const laterExpiry = await futureExpiry(3600);
    const secondId = ethers.id("revoked-dataset");
    await ledger.connect(provider).register(secondId, hash, 1, laterExpiry, false, false, [purpose], [region]);
    expect(await ledger.permits(secondId, purpose, region, false, false)).to.equal(true);
    await ledger.connect(provider).revoke(secondId);
    expect(await ledger.permits(secondId, purpose, region, false, false)).to.equal(false);
  });

  it("rejects invalid, zero, or duplicate permission entries", async function () {
    const [admin, provider] = await ethers.getSigners();
    const ledger = await deployLedger();
    await ledger.connect(admin).authorizeProvider(provider.address);
    const { hash, purpose, region } = validTerms();
    const expiry = await futureExpiry();

    await expect(ledger.connect(provider).register(ethers.id("zero-purpose"), hash, 1, expiry, false, false, [ethers.ZeroHash], [region]))
      .to.be.revertedWithCustomError(ledger, "InvalidInput");
    await expect(ledger.connect(provider).register(ethers.id("duplicate-purpose"), hash, 1, expiry, false, false, [purpose, purpose], [region]))
      .to.be.revertedWithCustomError(ledger, "InvalidInput");
  });
});
