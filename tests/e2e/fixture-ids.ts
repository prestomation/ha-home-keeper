/**
 * Ids of the seeded e2e fixtures.
 *
 * The seed stores real `uuid4`s — the shape `models.build_task` and
 * `assets.build_asset` mint, and the only shape a real install ever holds. Readable
 * ids were easier to grep for, but they were also far shorter than anything a user
 * sees, which quietly made every screenshot and layout assertion easier than reality:
 * the panel's id row wraps at a width no short fixture would ever have exercised.
 *
 * Specs reach for these names rather than pasting a uuid.
 */

/** Tasks. */
export const TASK = {
  anode: '25f086ad-91ce-4ca4-8f05-73b443565479',
  buddyMedicine: 'a5d646cc-ab00-471f-b945-73dda6080ddb',
  carRegistration: '4fa204b6-ff6b-4bab-96c7-c8128b462c06',
  doorBattery: '21720ccd-21e3-4171-abc7-639ec6ee00f4',
  fridgeFilter: '72347867-23a3-47f8-84d5-917be61e8a6d',
  furnaceFilter: 'c564261f-48a3-4434-b9ad-7c42a4ccf57a',
  medicine: '96e74181-ebe2-4b4c-97d0-781fc952924f',
  nozzleUsage: '14a593d8-07e3-4674-b589-1e27ff21a8ea',
  passport: 'e0eaf3f3-ab51-4a8e-a9c7-71d0c6001160',
  rexVet: '8ad982ca-e5f9-4f53-bebd-93a05e078844',
  smokeBattery: 'b61a0b0e-6838-46a9-89d5-7090f8b4aa35',
  thermostatBattery: '467606ef-4193-4541-bf6c-6509cfbf425e',
  waterFilter: 'acb13a18-979a-4812-8a00-2e4a426df8db',
} as const;

/** Appliances. */
export const ASSET = {
  radioShade: '23e02da0-0411-4b16-9a63-10126f2ca7e6',
  shades: '1f938cf8-c2a3-4438-aab3-840d0d749725',
  waterHeater: 'e8d76383-4067-415c-975f-2ee73f475fa1',
} as const;

/** Parts. */
export const PART = {
  anode: 'c91fd864-9e72-4645-9ab7-cdca418bb2bc',
  descaler: 'ae2b576d-67f4-4d4b-9aaf-d0bcebc5953b',
  sedimentFilter: 'f8319a3a-c717-48c2-a53e-79a205fb4a48',
  tpValve: '11a79824-31d5-4ccc-b5b9-12104ff7e327',
} as const;

/** Documents attached to the water heater. */
export const DOC = {
  manualPdf: '56656a41-c3a1-4db7-9adf-d1b0fb9e0c23',
} as const;

/** The water heater's metadata entries. */
export const META = {
  installDate: 'a16368b4-3f2a-4b7c-8ee9-a4cb76a3dbaf',
  notes: '7c4afbed-a448-4d7a-9a10-b0f940825161',
  purchaseDate: '8b2c3658-43b1-42ef-8811-7388b4616e83',
  reorderLink: '4f3ed25f-795d-42b3-865c-afaee7edcb98',
  vendor: '90eb41ad-9fa6-440d-92a7-2e8b215aa3c7',
  warrantyExpiry: 'f0c3b2f4-8c31-4ed4-a3ea-64aaa201af89',
  warrantyProvider: '949d3288-cc61-4bb3-963a-8cf7ac5ffeef',
} as const;
