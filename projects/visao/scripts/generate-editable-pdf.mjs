import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const requireFromFrontend = createRequire(
  new URL("../frontend/package.json", import.meta.url),
);
const {
  PDFDocument,
  PDFHexString,
  PDFName,
  StandardFonts,
  defaultTextFieldAppearanceProvider,
  drawCheckMark,
  drawEllipse,
  rgb,
} = requireFromFrontend("pdf-lib");

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.resolve(scriptDirectory, "..");
const sourcePath = path.join(
  projectDirectory,
  "media",
  "Checklist e Tratativas - Visão Vendas.pdf",
);
const outputPath = path.join(projectDirectory, "media", "editavel.pdf");

const sourceBytes = await readFile(sourcePath);
const pdf = await PDFDocument.load(sourceBytes);
const pages = pdf.getPages();

if (pages.length !== 4) {
  throw new Error(`Esperadas 4 páginas no original; encontradas ${pages.length}.`);
}

pdf.setTitle("Checklist e Tratativas - Visão Vendas — Editável");
pdf.setSubject("Ficha editável de checklist e tratativas para contrato");
pdf.setAuthor("Visão Imóveis");
pdf.setCreator("Visão Vendas");
pdf.setProducer("Visão Vendas / pdf-lib");

const form = pdf.getForm();
const font = await pdf.embedFont(StandardFonts.Helvetica);
const ink = rgb(0.055, 0.105, 0.16);
const checkInk = rgb(0, 0.333, 0.588);
const paper = rgb(1, 1, 1);
const expectedFields = new Set();

function filledAwareTextAppearance(field, widget, appearanceFont) {
  if (!field.getText()) return [];
  return defaultTextFieldAppearanceProvider(field, widget, appearanceFont);
}

function transparentCheckAppearance(_field, widget) {
  const { width, height } = widget.getRectangle();
  const mark = drawCheckMark({
    x: width / 2,
    y: height / 2,
    size: Math.min(width, height) / 2,
    thickness: 1.4,
    color: checkInk,
  });
  return {
    normal: { on: mark, off: [] },
    down: { on: mark, off: [] },
  };
}

function transparentRadioAppearance(_field, widget) {
  const { width, height } = widget.getRectangle();
  const dot = drawEllipse({
    x: width / 2,
    y: height / 2,
    xScale: Math.min(width, height) * 0.24,
    yScale: Math.min(width, height) * 0.24,
    color: checkInk,
    borderColor: undefined,
    borderWidth: 0,
  });
  return {
    normal: { on: dot, off: [] },
    down: { on: dot, off: [] },
  };
}

function describe(field, label) {
  field.acroField.dict.set(PDFName.of("TU"), PDFHexString.fromText(label));
}

function textField(name, pageIndex, rectangle, label, options = {}) {
  const [rawX, rawY, rawWidth, rawHeight] = rectangle;
  const inset = options.inset ?? 1;
  const x = rawX + inset;
  const y = rawY + inset;
  const width = rawWidth - (inset * 2);
  const height = rawHeight - (inset * 2);
  const field = form.createTextField(name);
  expectedFields.add(name);
  describe(field, label);
  if (options.multiline) field.enableMultiline();
  if (options.maxLength) field.setMaxLength(options.maxLength);
  field.addToPage(pages[pageIndex], {
    x,
    y,
    width,
    height,
    textColor: ink,
    backgroundColor: paper,
    borderColor: undefined,
    borderWidth: 0,
    font,
  });
  field.setFontSize(options.fontSize ?? (options.multiline ? 7 : 8));
  field.updateAppearances(font, filledAwareTextAppearance);
  return field;
}

function checkField(name, pageIndex, rectangle, label) {
  const [x, y, width, height] = rectangle;
  const field = form.createCheckBox(name);
  expectedFields.add(name);
  describe(field, label);
  field.addToPage(pages[pageIndex], {
    x,
    y,
    width,
    height,
    textColor: checkInk,
    backgroundColor: undefined,
    borderColor: undefined,
    borderWidth: 0,
  });
  field.updateAppearances(transparentCheckAppearance);
  return field;
}

function radioField(name, pageIndex, options, label) {
  const field = form.createRadioGroup(name);
  expectedFields.add(name);
  describe(field, label);
  for (const option of options) {
    const [value, x, y, width = 7, height = 7] = option;
    field.addOptionToPage(value, pages[pageIndex], {
      x,
      y,
      width,
      height,
      textColor: ink,
      borderWidth: 0,
    });
  }
  field.updateAppearances(transparentRadioAppearance);
  return field;
}

function checklistItem(id, pageIndex, checkRect, notesRect, label) {
  checkField(`checklist.${id}.checked`, pageIndex, checkRect, `${label}: recebido`);
  textField(
    `checklist.${id}.notes`,
    pageIndex,
    notesRect,
    `${label}: anotações / status da validação`,
    { multiline: true, maxLength: 600, fontSize: notesRect[2] < 80 ? 5.2 : 6.2 },
  );
}

// Página 1 — identificação e checklist documental.
textField("meta.date.day", 0, [451, 716, 18, 11], "Data do atendimento: dia", { maxLength: 2, fontSize: 7.5 });
textField("meta.date.month", 0, [478, 716, 18, 11], "Data do atendimento: mês", { maxLength: 2, fontSize: 7.5 });
textField("meta.date.year", 0, [522, 716, 12, 11], "Data do atendimento: ano após 20", { maxLength: 2, fontSize: 7.5 });
textField("meta.atendimento", 0, [151, 609, 144, 22], "Número do atendimento");
textField("meta.corretor", 0, [389, 609, 143, 22], "Nome do corretor responsável");

const pageOneChecklist = [
  ["seller.identity", 526, 516, 22, "Vendedores — RG / CPF ou CNH válida"],
  ["seller.civil", 496, 478, 37, "Vendedores — certidão de casamento ou nascimento"],
  ["seller.address", 463, 455, 22, "Vendedores — comprovante de endereço atualizado"],
  ["seller.profession", 441, 432, 22, "Vendedores — profissão atual"],
  ["seller.contacts", 419, 410, 21, "Vendedores — e-mails e telefones diretos"],
  ["buyer.identity", 330, 320, 22, "Compradores — RG / CPF ou CNH válida"],
  ["buyer.civil", 300, 281, 38, "Compradores — certidão de casamento ou nascimento"],
  ["buyer.address", 267, 258, 22, "Compradores — comprovante de endereço atualizado"],
  ["buyer.profession", 245, 236, 22, "Compradores — profissão atual"],
  ["buyer.contacts", 223, 214, 22, "Compradores — e-mails e telefones diretos"],
  ["buyer.income", 192, 173, 40, "Compradores — comprovante de renda"],
  ["buyer.tax", 160, 143, 29, "Compradores — declaração de Imposto de Renda e recibo"],
  ["company.contract", 38, 29, 20, "Pessoa jurídica — contrato de constituição e última alteração consolidada"],
];

for (const [id, checkY, noteY, noteHeight, label] of pageOneChecklist) {
  const noteX = id === "company.contract" ? 420 : 343;
  checklistItem(id, 0, [70.5, checkY, 9, 9], [noteX, noteY, 532 - noteX, noteHeight], label);
}

// Página 2 — continuação do checklist, imóvel e comprador.
const pageTwoChecklist = [
  ["company.cnpj", 797, 789, 21, "Pessoa jurídica — cartão de CNPJ e certidão simplificada"],
  ["company.representatives", 776, 752, 36, "Pessoa jurídica — documentação dos sócios e representantes"],
  ["property.registry", 710, 701, 22, "Imóvel — matrícula atualizada"],
  ["property.tax", 688, 679, 22, "Imóvel — espelho do IPTU e código interno"],
  ["property.condo", 667, 646, 34, "Imóvel — administradora e certidão negativa do condomínio"],
  ["property.utilities", 635, 625, 22, "Imóvel — contas de consumo quitadas"],
  ["property.finance", 612, 603, 22, "Imóvel — boleto de evolução do financiamento"],
];

for (const [id, checkY, noteY, noteHeight, label] of pageTwoChecklist) {
  const noteX = {
    "property.tax": 390,
    "property.utilities": 390,
    "property.condo": 460,
    "property.finance": 480,
  }[id] ?? 425;
  checklistItem(id, 1, [70.5, checkY, 9, 9], [noteX, noteY, 532 - noteX, noteHeight], label);
}

const propertyFields = [
  ["property.ref", [136, 379, 160, 22], "Referência no sistema"],
  ["property.value", [389, 379, 143, 22], "Valor do imóvel"],
  ["property.address", [136, 353, 396, 22], "Endereço do imóvel"],
  ["property.neighborhood", [136, 331, 160, 18], "Bairro ou condomínio"],
  ["property.registry", [370, 331, 162, 18], "Número da matrícula"],
  ["property.municipal", [136, 304, 160, 23], "Cadastro municipal"],
  ["property.origin", [370, 304, 162, 19], "Mídia ou origem"],
  ["property.broker", [136, 279, 160, 20], "Corretor"],
  ["property.capturer", [370, 279, 162, 20], "Captador"],
  ["property.partnership", [136, 253, 160, 21], "Parceria"],
  ["property.contact", [370, 253, 162, 24], "Forma de contato"],
];
for (const [name, rectangle, label] of propertyFields) textField(name, 1, rectangle, label);

const buyerPageTwoFields = [
  ["buyer.name", [143, 190, 389, 24], "Comprador — nome completo", 7.5],
  ["buyer.rg", [143, 160, 40, 19], "Comprador — RG", 5.2],
  ["buyer.cpf", [491, 160, 41, 19], "Comprador — CPF/MF", 4.5],
  ["buyer.nationality", [143, 139, 40, 18], "Comprador — nacionalidade", 5.2],
  ["buyer.civilStatus", [491, 139, 41, 18], "Comprador — estado civil", 5.2],
  ["buyer.profession", [143, 117, 389, 18], "Comprador — profissão", 7.5],
  ["buyer.address", [143, 90, 389, 23], "Comprador — endereço residencial", 7.5],
  ["buyer.neighborhood", [143, 68, 40, 18], "Comprador — bairro", 5.2],
  ["buyer.city", [491, 68, 41, 18], "Comprador — cidade e UF", 5.2],
  ["buyer.phones", [143, 45, 40, 18], "Comprador — telefones", 4.5],
  ["buyer.email", [491, 45, 41, 18], "Comprador — e-mail", 4.2],
];
for (const [name, rectangle, label, fontSize] of buyerPageTwoFields) textField(name, 1, rectangle, label, { fontSize });

function bankingFields(prefix, pageIndex, y, label) {
  textField(`${prefix}.bank`, pageIndex, [176, y, 73, 15], `${label} — banco`, { fontSize: 7 });
  textField(`${prefix}.agency`, pageIndex, [271, y, 36, 15], `${label} — agência`, { fontSize: 7 });
  textField(`${prefix}.account`, pageIndex, [328, y, 57, 15], `${label} — conta`, { fontSize: 7 });
  textField(`${prefix}.pix`, pageIndex, [405, y, 99, 15], `${label} — PIX`, { fontSize: 7 });
}

function compactPerson(prefix, pageIndex, coordinates, label) {
  const fields = [
    ["name", [143, coordinates.name, 389, 24], "nome completo", 7.5],
    ["rg", [143, coordinates.rg, 40, 18], "RG", 5.2],
    ["cpf", [491, coordinates.rg, 41, 18], "CPF/MF", 4.5],
    ["nationality", [143, coordinates.nationality, 40, 18], "nacionalidade", 5.2],
    ["civilStatus", [491, coordinates.nationality, 41, 18], "estado civil", 5.2],
    ["profession", [143, coordinates.profession, 389, 18], "profissão", 7.5],
    ["phones", [143, coordinates.phones, 40, 18], "telefones", 4.5],
    ["email", [491, coordinates.phones, 41, 18], "e-mail", 4.2],
  ];
  for (const [suffix, rectangle, fieldLabel, fontSize] of fields) {
    textField(`${prefix}.${suffix}`, pageIndex, rectangle, `${label} — ${fieldLabel}`, { fontSize });
  }
  bankingFields(prefix, pageIndex, coordinates.bank, label);
}

function fullPerson(prefix, pageIndex, coordinates, label) {
  compactPerson(prefix, pageIndex, coordinates, label);
  textField(`${prefix}.address`, pageIndex, [143, coordinates.address, 389, 27], `${label} — endereço residencial`, { fontSize: 7.5 });
  textField(`${prefix}.neighborhood`, pageIndex, [143, coordinates.neighborhood, 40, 18], `${label} — bairro`, { fontSize: 7.5 });
  textField(`${prefix}.city`, pageIndex, [491, coordinates.neighborhood, 41, 18], `${label} — cidade e UF`, { fontSize: 5.2 });
}

// Página 3 — dados bancários, demais partes e início das condições.
bankingFields("buyer", 2, 791, "Comprador");
radioField("buyer.accountType", 2, [
  ["corrente", 145, 784],
  ["poupanca", 199, 784],
], "Comprador — tipo de conta");

compactPerson("coBuyer", 2, {
  name: 718, rg: 689, nationality: 667, profession: 644, phones: 623, bank: 601,
}, "Cônjuge ou sócio co-comprador");

fullPerson("seller", 2, {
  name: 535, rg: 507, nationality: 485, profession: 462, address: 434,
  neighborhood: 413, phones: 391, bank: 371,
}, "Vendedor");
radioField("seller.accountType", 2, [
  ["corrente", 145, 365],
  ["poupanca", 199, 365],
], "Vendedor — tipo de conta");

compactPerson("coSeller", 2, {
  name: 299, rg: 271, nationality: 249, profession: 226, phones: 205, bank: 182,
}, "Cônjuge ou sócio co-vendedor");

textField("deal.totalValue", 2, [196, 107, 94, 18], "Valor total da venda");
textField("deal.registryValue", 2, [438, 107, 94, 18], "Valor para cartório");
textField("deal.depositValue", 2, [196, 82, 94, 18], "Valor do sinal ou entrada");
textField("deal.depositDate", 2, [420, 82, 112, 18], "Data ou quando será pago o sinal");
radioField("deal.depositMethod", 2, [
  ["pix", 182, 65],
  ["ted", 217, 65],
  ["cheque_administrativo", 254, 65],
], "Forma de pagamento do sinal");
textField("deal.installmentValue", 2, [438, 53, 94, 18], "Valor das intermediárias ou reforços");

// Página 4 — condições, comissão, posse, parceria e observações.
textField("deal.installmentDate", 3, [180, 782, 111, 22], "Data ou quando será paga a intermediária");
radioField("deal.installmentMethod", 3, [
  ["pix", 424, 795],
  ["ted", 459, 795],
  ["cheque_administrativo", 495, 795],
], "Forma de pagamento da intermediária");
textField("deal.financedValue", 3, [196, 758, 94, 18], "Valor financiado");
textField("deal.bank", 3, [420, 758, 112, 18], "Banco ou correspondente");
textField("deal.commissionValue", 3, [196, 736, 42, 18], "Valor da comissão", { fontSize: 7 });
textField("deal.commissionPercent", 3, [245, 736, 25, 18], "Percentual da comissão", { maxLength: 6, fontSize: 7 });
radioField("deal.invoice", 3, [
  ["sim", 424, 740],
  ["nao", 459, 740],
], "Emissão de nota fiscal");
radioField("deal.commissionMethod", 3, [
  ["pix", 182, 714],
  ["ted", 217, 714],
], "Forma de pagamento da comissão");
radioField("deal.payer", 3, [
  ["seller", 424, 714],
  ["buyer", 481, 714],
], "Responsável pelo pagamento da comissão");
radioField("deal.recipient", 3, [
  ["visao", 182, 687],
  ["split", 264, 687],
], "Destinatário da comissão");
textField("deal.commissionDate", 3, [420, 677, 112, 18], "Quando a comissão será paga");
radioField("deal.occupancy", 3, [
  ["owner", 182, 657],
  ["tenant", 247, 657],
  ["vacant", 225, 646],
], "Situação do imóvel");
radioField("deal.furniture", 3, [
  ["sim", 424, 653],
  ["nao", 459, 653],
], "Inclusão de mobília");
textField("deal.possessionDate", 3, [180, 613, 352, 20], "Data da entrega da posse");

const partnerFields = [
  ["partner.name", [134, 548, 230, 25], "Parceiro externo — nome"],
  ["partner.creci", [420, 548, 112, 25], "Parceiro externo — CRECI"],
  ["partner.document", [134, 522, 230, 20], "Parceiro externo — CPF ou CNPJ"],
  ["partner.phone", [420, 522, 112, 20], "Parceiro externo — telefone"],
  ["partner.email", [134, 500, 398, 19], "Parceiro externo — e-mail"],
];
for (const [name, rectangle, label] of partnerFields) textField(name, 3, rectangle, label, { fontSize: 7.5 });
textField("partner.bank", 3, [134, 463, 398, 34], "Parceiro externo — dados bancários ou PIX", { multiline: true, fontSize: 7 });
textField("deal.notes", 3, [62, 339, 472, 93], "Informações complementares e observações", { multiline: true, maxLength: 2500, fontSize: 8 });

if (expectedFields.size !== 139) {
  throw new Error(`Inventário incorreto antes da gravação: ${expectedFields.size} campos.`);
}

form.updateFieldAppearances(font);
const outputBytes = await pdf.save({
  addDefaultPage: false,
  useObjectStreams: false,
  updateFieldAppearances: true,
});
await writeFile(outputPath, outputBytes);

// Verificação estrutural no próprio artefato gravado.
const written = await PDFDocument.load(await readFile(outputPath));
const writtenForm = written.getForm();
const writtenFields = writtenForm.getFields();
const writtenNames = new Set(writtenFields.map((field) => field.getName()));
const missing = [...expectedFields].filter((name) => !writtenNames.has(name));
const readOnly = writtenFields.filter((field) => field.isReadOnly()).map((field) => field.getName());
const widgetCount = writtenFields.reduce(
  (total, field) => total + field.acroField.getWidgets().length,
  0,
);

if (written.getPageCount() !== 4 || writtenFields.length !== 139 || missing.length || readOnly.length || widgetCount !== 152) {
  throw new Error(JSON.stringify({
    pages: written.getPageCount(),
    fields: writtenFields.length,
    widgets: widgetCount,
    missing,
    readOnly,
  }, null, 2));
}

// Prova comportamental sem alterar o PDF vazio entregue ao cliente.
const proof = await PDFDocument.load(await readFile(outputPath));
const proofForm = proof.getForm();
proofForm.getTextField("buyer.name").setText("VALIDAÇÃO DE PREENCHIMENTO");
proofForm.getCheckBox("checklist.seller.identity.checked").check();
proofForm.getRadioGroup("deal.depositMethod").select("pix");
proofForm.getTextField("deal.notes").setText("Linha 1\nLinha 2");
proofForm.updateFieldAppearances(await proof.embedFont(StandardFonts.Helvetica));
const proofBytes = await proof.save({ updateFieldAppearances: true });
const reopenedProof = await PDFDocument.load(proofBytes);
const reopenedForm = reopenedProof.getForm();
const roundTrip =
  reopenedForm.getTextField("buyer.name").getText() === "VALIDAÇÃO DE PREENCHIMENTO"
  && reopenedForm.getCheckBox("checklist.seller.identity.checked").isChecked()
  && reopenedForm.getRadioGroup("deal.depositMethod").getSelected() === "pix"
  && reopenedForm.getTextField("deal.notes").getText() === "Linha 1\nLinha 2";

if (!roundTrip) throw new Error("A prova de preenchimento e reabertura falhou.");

console.log(JSON.stringify({
  output: outputPath,
  pages: written.getPageCount(),
  fields: writtenFields.length,
  widgets: widgetCount,
  bytes: outputBytes.length,
  editable: true,
  fillSaveReopen: roundTrip,
}, null, 2));
