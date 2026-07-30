import { createRequire } from "node:module";
import { writeFile, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const requireFromFrontend = createRequire(new URL("../frontend/package.json", import.meta.url));
const {
  PDFDocument,
  PDFHexString,
  PDFName,
  StandardFonts,
  drawCheckMark,
  drawEllipse,
  rgb,
} = requireFromFrontend("pdf-lib");

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.resolve(scriptDirectory, "..");
const outputPath = path.join(projectDirectory, "media", "editavel-v3.pdf");

const PAGE_WIDTH = 595.28;
const PAGE_HEIGHT = 841.89;
const MARGIN = 42;
const CONTENT_WIDTH = PAGE_WIDTH - (MARGIN * 2);
const GAP = 12;

const colors = {
  blue: rgb(0, 85 / 255, 150 / 255),
  blueDeep: rgb(0, 63 / 255, 112 / 255),
  bluePale: rgb(232 / 255, 241 / 255, 247 / 255),
  red: rgb(217 / 255, 26 / 255, 26 / 255),
  redPale: rgb(254 / 255, 242 / 255, 242 / 255),
  ink: rgb(30 / 255, 41 / 255, 59 / 255),
  muted: rgb(100 / 255, 116 / 255, 139 / 255),
  line: rgb(203 / 255, 213 / 255, 225 / 255),
  paper: rgb(1, 1, 1),
};

const pdf = await PDFDocument.create();
pdf.setTitle("Checklist e Tratativas - Visão Vendas — Editável V3");
pdf.setSubject("Formulário AcroForm redesenhado para preenchimento digital");
pdf.setAuthor("Visão Imóveis");
pdf.setCreator("Visão Vendas");
pdf.setProducer("Visão Vendas / pdf-lib");

const regular = await pdf.embedFont(StandardFonts.Helvetica);
const bold = await pdf.embedFont(StandardFonts.HelveticaBold);
const brandImage = await pdf.embedPng(await readFile(path.join(projectDirectory, "media", "visao-brand.png")));
const form = pdf.getForm();
const expectedFields = new Set();
const widgetRects = [];

function tooltip(field, label) {
  field.acroField.dict.set(PDFName.of("TU"), PDFHexString.fromText(label));
}

function registerRect(pageIndex, name, rectangle) {
  const [x, y, width, height] = rectangle;
  if (x < 0 || y < 0 || x + width > PAGE_WIDTH || y + height > PAGE_HEIGHT) {
    throw new Error(`Campo fora da página: ${name} em ${JSON.stringify(rectangle)}`);
  }
  widgetRects.push({ pageIndex, name, x, y, width, height });
}

function transparentCheckAppearance(_field, widget) {
  const { width, height } = widget.getRectangle();
  const mark = drawCheckMark({
    x: width / 2,
    y: height / 2,
    size: Math.min(width, height) * 0.42,
    thickness: 1.5,
    color: colors.blue,
  });
  return { normal: { on: mark, off: [] }, down: { on: mark, off: [] } };
}

function transparentRadioAppearance(_field, widget) {
  const { width, height } = widget.getRectangle();
  const dot = drawEllipse({
    x: width / 2,
    y: height / 2,
    xScale: Math.min(width, height) * 0.24,
    yScale: Math.min(width, height) * 0.24,
    color: colors.blue,
    borderColor: undefined,
    borderWidth: 0,
  });
  return { normal: { on: dot, off: [] }, down: { on: dot, off: [] } };
}

function drawBrand(page) {
  page.drawImage(brandImage, { x: MARGIN, y: 781, width: 130, height: 40 });
}

function addPage(title, subtitle) {
  const page = pdf.addPage([PAGE_WIDTH, PAGE_HEIGHT]);
  const pageIndex = pdf.getPageCount() - 1;
  page.drawRectangle({ x: 0, y: 0, width: PAGE_WIDTH, height: PAGE_HEIGHT, color: colors.paper });
  drawBrand(page);
  page.drawText(title, { x: 214, y: 799, font: bold, size: 13.5, color: colors.blueDeep });
  page.drawText(subtitle, { x: 214, y: 784, font: regular, size: 7.2, color: colors.muted });
  page.drawLine({ start: { x: MARGIN, y: 770 }, end: { x: PAGE_WIDTH - MARGIN, y: 770 }, thickness: 1.8, color: colors.blue });
  page.drawText(`VISÃO VENDAS  •  FORMULÁRIO EDITÁVEL V3  •  PÁGINA ${pageIndex + 1}`, {
    x: MARGIN,
    y: 24,
    font: bold,
    size: 6,
    color: colors.muted,
  });
  page.drawLine({ start: { x: MARGIN, y: 35 }, end: { x: PAGE_WIDTH - MARGIN, y: 35 }, thickness: 0.5, color: colors.line });
  return { page, pageIndex, y: 744 };
}

function section(ctx, title, description = "") {
  const { page } = ctx;
  page.drawRectangle({ x: MARGIN, y: ctx.y - 25, width: CONTENT_WIDTH, height: 25, color: colors.blue });
  page.drawRectangle({ x: MARGIN, y: ctx.y - 25, width: 4, height: 25, color: colors.red });
  page.drawText(title, { x: MARGIN + 12, y: ctx.y - 17, font: bold, size: 8.5, color: colors.paper });
  ctx.y -= 34;
  if (description) {
    page.drawText(description, { x: MARGIN + 2, y: ctx.y - 7, font: regular, size: 6.5, color: colors.muted });
    ctx.y -= 18;
  }
}

function addTextField(ctx, name, label, x, top, width, options = {}) {
  const height = options.height ?? 27;
  const boxY = top - height;
  const labelColor = options.required ? colors.red : colors.ink;
  ctx.page.drawText(options.required ? `${label} *` : label, {
    x,
    y: top + 4,
    font: bold,
    size: 6.4,
    color: labelColor,
  });
  ctx.page.drawRectangle({
    x,
    y: boxY,
    width,
    height,
    color: colors.paper,
    borderColor: options.required ? colors.blue : colors.line,
    borderWidth: options.required ? 0.9 : 0.65,
  });

  const inset = 4;
  const widget = [x + inset, boxY + inset, width - (inset * 2), height - (inset * 2)];
  const field = form.createTextField(name);
  expectedFields.add(name);
  tooltip(field, label);
  if (options.multiline) field.enableMultiline();
  if (options.maxLength) field.setMaxLength(options.maxLength);
  field.addToPage(ctx.page, {
    x: widget[0], y: widget[1], width: widget[2], height: widget[3],
    font: regular,
    textColor: colors.ink,
    backgroundColor: undefined,
    borderColor: undefined,
    borderWidth: 0,
  });
  field.setFontSize(options.fontSize ?? (options.multiline ? 7.2 : 8));
  registerRect(ctx.pageIndex, name, widget);
  return field;
}

function row(ctx, fields, options = {}) {
  const top = ctx.y - 9;
  let x = MARGIN;
  const available = CONTENT_WIDTH - (GAP * (fields.length - 1));
  const totalUnits = fields.reduce((sum, field) => sum + (field.units ?? 1), 0);
  const height = options.height ?? Math.max(...fields.map((field) => field.height ?? 27));
  for (const field of fields) {
    const width = available * ((field.units ?? 1) / totalUnits);
    addTextField(ctx, field.name, field.label, x, top, width, { ...field, height: field.height ?? height });
    x += width + GAP;
  }
  ctx.y -= height + 23;
}

function addCheckField(ctx, name, x, centerY, label) {
  const size = 12;
  const y = centerY - (size / 2);
  ctx.page.drawRectangle({ x, y, width: size, height: size, color: colors.paper, borderColor: colors.blue, borderWidth: 1 });
  const field = form.createCheckBox(name);
  expectedFields.add(name);
  tooltip(field, label);
  field.addToPage(ctx.page, { x, y, width: size, height: size, textColor: colors.blue, backgroundColor: undefined, borderColor: undefined, borderWidth: 0 });
  field.updateAppearances(transparentCheckAppearance);
  registerRect(ctx.pageIndex, name, [x, y, size, size]);
}

function addRadioField(ctx, name, label, top, options) {
  ctx.page.drawText(label, { x: MARGIN, y: top, font: bold, size: 6.4, color: colors.ink });
  const field = form.createRadioGroup(name);
  expectedFields.add(name);
  tooltip(field, label);
  let x = MARGIN;
  const y = top - 25;
  for (const option of options) {
    const size = 12;
    ctx.page.drawCircle({ x: x + 6, y: y + 6, size: 6, color: colors.paper, borderColor: colors.blue, borderWidth: 1 });
    field.addOptionToPage(option.value, ctx.page, { x, y, width: size, height: size, textColor: colors.blue, borderWidth: 0 });
    registerRect(ctx.pageIndex, `${name}:${option.value}`, [x, y, size, size]);
    ctx.page.drawText(option.label, { x: x + 17, y: y + 2.5, font: regular, size: 7.4, color: colors.ink });
    x += 23 + regular.widthOfTextAtSize(option.label, 7.4) + 18;
  }
  field.updateAppearances(transparentRadioAppearance);
  ctx.y = top - 39;
}

function checklistRow(ctx, item) {
  const rowHeight = item.detail ? 39 : 34;
  const rowBottom = ctx.y - rowHeight;
  ctx.page.drawRectangle({ x: MARGIN, y: rowBottom, width: CONTENT_WIDTH, height: rowHeight, color: colors.paper, borderColor: colors.line, borderWidth: 0.45 });
  addCheckField(ctx, `checklist.${item.id}.checked`, MARGIN + 10, rowBottom + (rowHeight / 2), `${item.title}: recebido`);
  ctx.page.drawText(item.title, { x: MARGIN + 32, y: ctx.y - 14, font: bold, size: 7.1, color: colors.ink });
  if (item.detail) ctx.page.drawText(item.detail, { x: MARGIN + 32, y: ctx.y - 26, font: regular, size: 5.8, color: colors.muted });
  const notesX = 344;
  ctx.page.drawText("TRATATIVA / STATUS", { x: notesX, y: ctx.y - 10, font: bold, size: 5.5, color: colors.muted });
  addTextField(ctx, `checklist.${item.id}.notes`, "", notesX, ctx.y - 12, PAGE_WIDTH - MARGIN - notesX, {
    height: rowHeight - 17,
    fontSize: 6.4,
    multiline: rowHeight > 34,
    maxLength: 600,
  });
  ctx.y = rowBottom - 5;
}

function personSection(ctx, prefix, title, options = {}) {
  section(ctx, title, options.description ?? "");
  row(ctx, [{ name: `${prefix}.name`, label: "NOME COMPLETO", units: 1, required: options.required }]);
  row(ctx, [
    { name: `${prefix}.rg`, label: "RG", units: 0.7 },
    { name: `${prefix}.cpf`, label: "CPF/MF", units: 1.3, required: options.required },
  ]);
  row(ctx, [
    { name: `${prefix}.nationality`, label: "NACIONALIDADE", units: 0.8 },
    { name: `${prefix}.civilStatus`, label: "ESTADO CIVIL", units: 1.2 },
  ]);
  row(ctx, [{ name: `${prefix}.profession`, label: "PROFISSÃO", units: 1 }]);
  if (options.full) {
    row(ctx, [{ name: `${prefix}.address`, label: "ENDEREÇO RESIDENCIAL", units: 1 }]);
    row(ctx, [
      { name: `${prefix}.neighborhood`, label: "BAIRRO", units: 0.8 },
      { name: `${prefix}.city`, label: "CIDADE / UF", units: 1.2 },
    ]);
  }
  row(ctx, [
    { name: `${prefix}.phones`, label: "TELEFONES", units: 0.8 },
    { name: `${prefix}.email`, label: "E-MAIL", units: 1.2, required: prefix === "buyer" },
  ]);
}

function bankingRow(ctx, prefix, title = "DADOS BANCÁRIOS") {
  row(ctx, [
    { name: `${prefix}.bank`, label: `${title} — BANCO`, units: 1.1 },
    { name: `${prefix}.agency`, label: "AGÊNCIA", units: 0.65 },
    { name: `${prefix}.account`, label: "CONTA", units: 0.8 },
    { name: `${prefix}.pix`, label: "CHAVE PIX", units: 1.45 },
  ]);
}

const sellerChecklist = [
  { id: "seller.identity", title: "RG / CPF ou CNH válida", detail: "De todos os vendedores." },
  { id: "seller.civil", title: "Certidão de casamento ou nascimento", detail: "Incluir pacto antenupcial registrado, quando houver." },
  { id: "seller.address", title: "Comprovante de endereço atualizado", detail: "Emitido há no máximo 90 dias." },
  { id: "seller.profession", title: "Profissão atual" },
  { id: "seller.contacts", title: "E-mails e telefones diretos" },
];
const buyerChecklist = [
  { id: "buyer.identity", title: "RG / CPF ou CNH válida", detail: "De todos os compradores." },
  { id: "buyer.civil", title: "Certidão de casamento ou nascimento", detail: "Incluir pacto antenupcial registrado, quando houver." },
  { id: "buyer.address", title: "Comprovante de endereço atualizado", detail: "Emitido há no máximo 90 dias." },
  { id: "buyer.profession", title: "Profissão atual" },
  { id: "buyer.contacts", title: "E-mails e telefones diretos" },
  { id: "buyer.income", title: "Comprovante de renda", detail: "Seis holerites ou seis meses de extratos completos para autônomos." },
  { id: "buyer.tax", title: "Declaração de Imposto de Renda + recibo", detail: "Dispensada somente para perfis legalmente isentos." },
];
const companyChecklist = [
  { id: "company.contract", title: "Contrato de constituição e última alteração consolidada" },
  { id: "company.cnpj", title: "Cartão de CNPJ ativo e certidão simplificada" },
  { id: "company.representatives", title: "Documentos dos sócios e representantes", detail: "Identidade, estado civil, endereço, e-mail e telefones dos assinantes." },
];
const propertyChecklist = [
  { id: "property.registry", title: "Matrícula atualizada", detail: "Com ônus e ações; emissão nos últimos 30 dias." },
  { id: "property.tax", title: "Espelho do IPTU e código interno" },
  { id: "property.condo", title: "Administradora e certidão negativa do condomínio", detail: "Obrigatório quando o imóvel estiver em condomínio." },
  { id: "property.utilities", title: "Últimas contas de consumo quitadas", detail: "Água, energia e gás." },
  { id: "property.finance", title: "Último boleto de evolução do financiamento", detail: "Quando houver saldo devedor." },
];

// Página 1 — identificação e documentos de pessoas físicas.
{
  const ctx = addPage("CHECKLIST E TRATATIVAS", "Atendimento e documentação de pessoas físicas");
  section(ctx, "IDENTIFICAÇÃO DO ATENDIMENTO");
  row(ctx, [
    { name: "meta.date.day", label: "DIA", units: 0.32, maxLength: 2, fontSize: 9, required: true },
    { name: "meta.date.month", label: "MÊS", units: 0.32, maxLength: 2, fontSize: 9, required: true },
    { name: "meta.date.year", label: "ANO", units: 0.42, maxLength: 4, fontSize: 9, required: true },
    { name: "meta.atendimento", label: "Nº DO ATENDIMENTO", units: 1.45, required: true },
    { name: "meta.corretor", label: "CORRETOR RESPONSÁVEL", units: 2.3, required: true },
  ]);
  section(ctx, "DOCUMENTOS DOS VENDEDORES");
  for (const item of sellerChecklist) checklistRow(ctx, item);
  section(ctx, "DOCUMENTOS DOS COMPRADORES");
  for (const item of buyerChecklist) checklistRow(ctx, item);
}

// Página 2 — pessoa jurídica e imóvel.
{
  const ctx = addPage("CHECKLIST DOCUMENTAL", "Pessoa jurídica, imóvel e instruções de encaminhamento");
  section(ctx, "DOCUMENTOS DE PESSOA JURÍDICA", "Preencher somente quando houver participante PJ.");
  for (const item of companyChecklist) checklistRow(ctx, item);
  section(ctx, "DOCUMENTOS E DADOS TÉCNICOS DO IMÓVEL");
  for (const item of propertyChecklist) checklistRow(ctx, item);
  ctx.page.drawRectangle({ x: MARGIN, y: ctx.y - 102, width: CONTENT_WIDTH, height: 94, color: colors.redPale, borderColor: colors.red, borderWidth: 0.7 });
  ctx.page.drawText("INSTRUÇÃO OBRIGATÓRIA DE ENVIO AO JURÍDICO", { x: MARGIN + 14, y: ctx.y - 28, font: bold, size: 8, color: colors.red });
  ctx.page.drawText("Junte toda a documentação em PDF, anexe esta ficha à proposta assinada e envie para:", { x: MARGIN + 14, y: ctx.y - 45, font: regular, size: 7, color: colors.ink });
  ctx.page.drawText("adriana.larangeira@visaoimoveis.imb.br  •  tiago.amadio@gmail.com  •  dany.corral@visaoimoveis.imb.br", { x: MARGIN + 14, y: ctx.y - 64, font: bold, size: 6.4, color: colors.blueDeep });
  ctx.page.drawText("Não encaminhar sem o número de atendimento devidamente preenchido.", { x: MARGIN + 14, y: ctx.y - 82, font: regular, size: 6.6, color: colors.muted });
}

// Página 3 — imóvel e comprador principal.
{
  const ctx = addPage("FICHA DE TRATATIVAS", "Dados cadastrais do imóvel e do comprador principal");
  section(ctx, "DADOS CADASTRAIS DO IMÓVEL");
  row(ctx, [
    { name: "property.ref", label: "REFERÊNCIA NO SISTEMA", required: true },
    { name: "property.value", label: "VALOR DO IMÓVEL (R$)", required: true },
  ]);
  row(ctx, [{ name: "property.address", label: "ENDEREÇO COMPLETO", required: true }]);
  row(ctx, [
    { name: "property.neighborhood", label: "BAIRRO / CONDOMÍNIO" },
    { name: "property.registry", label: "MATRÍCULA Nº" },
  ]);
  row(ctx, [
    { name: "property.municipal", label: "CADASTRO MUNICIPAL" },
    { name: "property.origin", label: "MÍDIA / ORIGEM" },
  ]);
  row(ctx, [
    { name: "property.broker", label: "CORRETOR" },
    { name: "property.capturer", label: "CAPTADOR" },
  ]);
  row(ctx, [
    { name: "property.partnership", label: "PARCERIA" },
    { name: "property.contact", label: "FORMA DE CONTATO" },
  ]);
  personSection(ctx, "buyer", "DADOS DO COMPRADOR PRINCIPAL", { full: true, required: true });
}

// Página 4 — dados bancários do comprador e co-comprador.
{
  const ctx = addPage("PARTES COMPRADORAS", "Dados bancários e participante co-comprador");
  section(ctx, "DADOS BANCÁRIOS DO COMPRADOR PRINCIPAL");
  bankingRow(ctx, "buyer");
  addRadioField(ctx, "buyer.accountType", "TIPO DE CONTA", ctx.y - 2, [
    { value: "corrente", label: "Conta corrente" },
    { value: "poupanca", label: "Conta poupança" },
  ]);
  personSection(ctx, "coBuyer", "CÔNJUGE OU SÓCIO CO-COMPRADOR", { description: "Preencher somente quando houver outra parte compradora." });
  bankingRow(ctx, "coBuyer");
}

// Página 5 — vendedor principal.
{
  const ctx = addPage("VENDEDOR PRINCIPAL", "Dados pessoais, contatos e recebimento");
  personSection(ctx, "seller", "DADOS DO VENDEDOR PRINCIPAL", { full: true, required: true });
  bankingRow(ctx, "seller");
  addRadioField(ctx, "seller.accountType", "TIPO DE CONTA DO VENDEDOR", ctx.y - 2, [
    { value: "corrente", label: "Conta corrente" },
    { value: "poupanca", label: "Conta poupança" },
  ]);
}

// Página 6 — co-vendedor.
{
  const ctx = addPage("CO-VENDEDOR", "Cônjuge ou sócio da parte vendedora");
  personSection(ctx, "coSeller", "CÔNJUGE OU SÓCIO CO-VENDEDOR", { description: "Preencher somente quando houver outra parte vendedora." });
  bankingRow(ctx, "coSeller");
}

// Página 7 — condições financeiras e comissão.
{
  const ctx = addPage("CONDIÇÕES DO NEGÓCIO", "Valores, pagamentos, financiamento e comissão");
  section(ctx, "ALINHAMENTO FINANCEIRO");
  row(ctx, [
    { name: "deal.totalValue", label: "VALOR TOTAL DA VENDA (R$)", required: true },
    { name: "deal.registryValue", label: "VALOR PARA CARTÓRIO (R$)" },
  ]);
  row(ctx, [
    { name: "deal.depositValue", label: "VALOR DO SINAL / ENTRADA (R$)" },
    { name: "deal.depositDate", label: "DATA DO SINAL", maxLength: 10 },
  ]);
  addRadioField(ctx, "deal.depositMethod", "FORMA DE PAGAMENTO DO SINAL", ctx.y - 2, [
    { value: "pix", label: "PIX" },
    { value: "ted", label: "TED" },
    { value: "cheque_administrativo", label: "Cheque administrativo" },
  ]);
  row(ctx, [
    { name: "deal.installmentValue", label: "INTERMEDIÁRIAS / REFORÇOS (R$)" },
    { name: "deal.installmentDate", label: "DATA DA INTERMEDIÁRIA", maxLength: 10 },
  ]);
  addRadioField(ctx, "deal.installmentMethod", "FORMA DE PAGAMENTO DA INTERMEDIÁRIA", ctx.y - 2, [
    { value: "pix", label: "PIX" },
    { value: "ted", label: "TED" },
    { value: "cheque_administrativo", label: "Cheque administrativo" },
  ]);
  row(ctx, [
    { name: "deal.financedValue", label: "VALOR FINANCIADO (R$)" },
    { name: "deal.bank", label: "BANCO / CORRESPONDENTE" },
  ]);
  section(ctx, "COMISSÃO");
  row(ctx, [
    { name: "deal.commissionValue", label: "VALOR DA COMISSÃO (R$)", units: 1.3 },
    { name: "deal.commissionPercent", label: "PERCENTUAL (%)", units: 0.7, maxLength: 6 },
  ]);
  addRadioField(ctx, "deal.invoice", "EMISSÃO DE NOTA FISCAL", ctx.y - 2, [
    { value: "sim", label: "Sim" },
    { value: "nao", label: "Não" },
  ]);
  addRadioField(ctx, "deal.commissionMethod", "FORMA DE PAGAMENTO DA COMISSÃO", ctx.y - 2, [
    { value: "pix", label: "PIX" },
    { value: "ted", label: "TED" },
  ]);
  addRadioField(ctx, "deal.payer", "RESPONSÁVEL PELO PAGAMENTO", ctx.y - 2, [
    { value: "seller", label: "Vendedor" },
    { value: "buyer", label: "Comprador" },
  ]);
  addRadioField(ctx, "deal.recipient", "DESTINATÁRIO DA COMISSÃO", ctx.y - 2, [
    { value: "visao", label: "Exclusivo Visão" },
    { value: "split", label: "Dividido" },
  ]);
  row(ctx, [{ name: "deal.commissionDate", label: "DATA PREVISTA PARA PAGAMENTO DA COMISSÃO", maxLength: 10 }]);
}

// Página 8 — posse, parceria e observações.
{
  const ctx = addPage("POSSE E INFORMAÇÕES FINAIS", "Situação do imóvel, parceria externa e observações");
  section(ctx, "SITUAÇÃO E POSSE");
  addRadioField(ctx, "deal.occupancy", "SITUAÇÃO DO IMÓVEL", ctx.y - 2, [
    { value: "owner", label: "Proprietário" },
    { value: "tenant", label: "Inquilino" },
    { value: "vacant", label: "Vago" },
  ]);
  addRadioField(ctx, "deal.furniture", "INCLUSÃO DE MOBÍLIA", ctx.y - 2, [
    { value: "sim", label: "Sim" },
    { value: "nao", label: "Não" },
  ]);
  row(ctx, [{ name: "deal.possessionDate", label: "DATA DA ENTREGA DA POSSE", maxLength: 10 }]);
  section(ctx, "PARCERIA EXTERNA", "Preencher somente quando houver parceiro externo.");
  row(ctx, [
    { name: "partner.name", label: "NOME DO PARCEIRO", units: 1.5 },
    { name: "partner.creci", label: "CRECI", units: 0.5 },
  ]);
  row(ctx, [
    { name: "partner.document", label: "CPF / CNPJ", units: 1.2 },
    { name: "partner.phone", label: "TELEFONE", units: 0.8 },
  ]);
  row(ctx, [{ name: "partner.email", label: "E-MAIL" }]);
  row(ctx, [{ name: "partner.bank", label: "DADOS BANCÁRIOS / PIX", height: 42, multiline: true }], { height: 42 });
  section(ctx, "INFORMAÇÕES COMPLEMENTARES E OBSERVAÇÕES");
  row(ctx, [{ name: "deal.notes", label: "CONDIÇÕES, EXCEÇÕES E ORIENTAÇÕES PARA O CONTRATO", height: 128, multiline: true, maxLength: 2500 }], { height: 128 });
}

if (expectedFields.size !== 139) {
  throw new Error(`Inventário V3 incorreto: ${expectedFields.size} campos; esperados 139.`);
}

// Campos de texto e controles jamais podem ocupar a mesma área na mesma página.
for (let index = 0; index < widgetRects.length; index += 1) {
  const a = widgetRects[index];
  for (let otherIndex = index + 1; otherIndex < widgetRects.length; otherIndex += 1) {
    const b = widgetRects[otherIndex];
    if (a.pageIndex !== b.pageIndex) continue;
    const overlaps = a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
    if (overlaps) throw new Error(`Widgets sobrepostos na página ${a.pageIndex + 1}: ${a.name} e ${b.name}`);
  }
}

form.updateFieldAppearances(regular);
const outputBytes = await pdf.save({ addDefaultPage: false, useObjectStreams: false, updateFieldAppearances: true });
await writeFile(outputPath, outputBytes);

const reopened = await PDFDocument.load(await readFile(outputPath));
const reopenedFields = reopened.getForm().getFields();
const widgetCount = reopenedFields.reduce((sum, field) => sum + field.acroField.getWidgets().length, 0);
if (reopened.getPageCount() !== 8 || reopenedFields.length !== 139 || widgetCount !== 152) {
  throw new Error(JSON.stringify({ pages: reopened.getPageCount(), fields: reopenedFields.length, widgets: widgetCount }));
}

const proof = await PDFDocument.load(await readFile(outputPath));
const proofForm = proof.getForm();
proofForm.getTextField("buyer.name").setText("NOME COMPLETO DE TESTE");
proofForm.getTextField("buyer.cpf").setText("123.456.789-00");
proofForm.getCheckBox("checklist.seller.identity.checked").check();
proofForm.getRadioGroup("deal.depositMethod").select("pix");
proofForm.getTextField("deal.notes").setText("Linha 1\nLinha 2");
proofForm.updateFieldAppearances(await proof.embedFont(StandardFonts.Helvetica));
const proofBytes = await proof.save({ updateFieldAppearances: true });
const proofReopened = await PDFDocument.load(proofBytes);
const proofReopenedForm = proofReopened.getForm();
const roundTrip =
  proofReopenedForm.getTextField("buyer.name").getText() === "NOME COMPLETO DE TESTE"
  && proofReopenedForm.getTextField("buyer.cpf").getText() === "123.456.789-00"
  && proofReopenedForm.getCheckBox("checklist.seller.identity.checked").isChecked()
  && proofReopenedForm.getRadioGroup("deal.depositMethod").getSelected() === "pix"
  && proofReopenedForm.getTextField("deal.notes").getText() === "Linha 1\nLinha 2";
if (!roundTrip) throw new Error("A prova V3 de preenchimento, salvamento e reabertura falhou.");

console.log(JSON.stringify({
  output: outputPath,
  pages: reopened.getPageCount(),
  fields: reopenedFields.length,
  widgets: widgetCount,
  bytes: outputBytes.length,
  overlapCheck: "passed",
  fillSaveReopen: roundTrip,
}, null, 2));
