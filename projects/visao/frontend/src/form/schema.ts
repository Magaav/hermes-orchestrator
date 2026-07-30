import type { FormField } from "./types";

export type ChecklistDocument = {
  id: string;
  title: string;
  detail?: string;
};

export type ChecklistGroup = {
  id: string;
  title: string;
  description: string;
  optional?: boolean;
  documents: ChecklistDocument[];
};

export type FormGroup = {
  id: string;
  title: string;
  description?: string;
  fields: FormField[];
  enabledBy?: string;
};

export type FormStep = {
  id: string;
  index: string;
  shortTitle: string;
  title: string;
  description: string;
};

const yesNo = [
  { value: "", label: "Selecione" },
  { value: "sim", label: "Sim" },
  { value: "nao", label: "Não" }
];

const paymentOptions = [
  { value: "", label: "Selecione" },
  { value: "pix", label: "PIX" },
  { value: "ted", label: "TED" },
  { value: "cheque_administrativo", label: "Cheque administrativo" },
  { value: "outro", label: "Outro" }
];

export const requiredFieldKeys = [
  "meta.date", "meta.atendimento", "meta.corretor", "property.ref", "property.value", "property.address",
  "buyer.name", "buyer.cpf", "buyer.email", "seller.name", "seller.cpf", "deal.totalValue"
];

export const steps: FormStep[] = [
  { id: "start", index: "01", shortTitle: "Atendimento", title: "Identificação do atendimento", description: "Abra o processo e registre quem está conduzindo a venda." },
  { id: "checklist", index: "02", shortTitle: "Documentos", title: "Checklist documental", description: "Valide os PDFs obrigatórios de cada participante e do imóvel." },
  { id: "property", index: "03", shortTitle: "Imóvel", title: "Dados cadastrais do imóvel", description: "Preencha a referência, valores e identificação completa do imóvel." },
  { id: "people", index: "04", shortTitle: "Partes", title: "Compradores e vendedores", description: "Cadastre as partes, contatos e dados bancários para o contrato." },
  { id: "deal", index: "05", shortTitle: "Negócio", title: "Condições do negócio", description: "Formalize pagamentos, financiamento, comissão, posse e parceria." },
  { id: "review", index: "06", shortTitle: "Revisão", title: "Revisão e envio", description: "Confira pendências, imprima uma cópia e envie o processo finalizado." }
];

export const startGroups: FormGroup[] = [{
  id: "identification",
  title: "Gestão de processos integrada",
  description: "O rascunho é salvo automaticamente enquanto você preenche.",
  fields: [
    { key: "meta.date", label: "Data do atendimento", type: "date", required: true },
    { key: "meta.atendimento", label: "Nº do atendimento", required: true, placeholder: "Ex.: 2026-00184" },
    { key: "meta.corretor", label: "Nome do corretor", required: true, placeholder: "Nome completo" },
    { key: "meta.city", label: "Cidade", placeholder: "Indaiatuba", help: "A ficha original usa Indaiatuba como local de emissão." }
  ]
}];

export const checklistGroups: ChecklistGroup[] = [
  {
    id: "seller",
    title: "Pessoa física — vendedores",
    description: "Documentos de todos os vendedores, estritamente em PDF.",
    documents: [
      { id: "seller.identity", title: "RG / CPF ou CNH válida", detail: "De todos os vendedores." },
      { id: "seller.civil", title: "Certidão de casamento ou nascimento", detail: "Para solteiros, anexar certidão de nascimento e pacto antenupcial registrado, se houver." },
      { id: "seller.address", title: "Comprovante de endereço atualizado", detail: "Emitido há no máximo 90 dias." },
      { id: "seller.profession", title: "Profissão atual" },
      { id: "seller.contacts", title: "E-mails e telefones diretos" }
    ]
  },
  {
    id: "buyer",
    title: "Pessoa física — compradores",
    description: "Documentos de todos os compradores, estritamente em PDF.",
    documents: [
      { id: "buyer.identity", title: "RG / CPF ou CNH válida", detail: "De todos os compradores." },
      { id: "buyer.civil", title: "Certidão de casamento ou nascimento", detail: "Para solteiros, anexar certidão de nascimento e pacto antenupcial registrado, se houver." },
      { id: "buyer.address", title: "Comprovante de endereço atualizado", detail: "Emitido há no máximo 90 dias." },
      { id: "buyer.profession", title: "Profissão atual" },
      { id: "buyer.contacts", title: "E-mails e telefones diretos" },
      { id: "buyer.income", title: "Comprovante de renda", detail: "Seis últimos holerites. Para autônomos, extratos bancários completos dos últimos seis meses." },
      { id: "buyer.tax", title: "Declaração de Imposto de Renda + recibo", detail: "Dispensado apenas para perfis legalmente isentos." }
    ]
  },
  {
    id: "company",
    title: "Pessoa jurídica",
    description: "Preencha somente quando houver participante PJ.",
    optional: true,
    documents: [
      { id: "company.contract", title: "Contrato de constituição e última alteração consolidada" },
      { id: "company.cnpj", title: "Cartão de CNPJ ativo e certidão simplificada da Junta Comercial" },
      { id: "company.representatives", title: "Documentação dos sócios e representantes", detail: "RG/CPF/CNH, estado civil, endereço, e-mail e telefones dos assinantes." }
    ]
  },
  {
    id: "property",
    title: "Imóvel",
    description: "Documentação e dados técnicos do imóvel.",
    documents: [
      { id: "property.registry", title: "Matrícula atualizada", detail: "Com ônus e ações, emitida nos últimos 30 dias." },
      { id: "property.tax", title: "Espelho do IPTU e código do imóvel no sistema interno" },
      { id: "property.condo", title: "Administradora e certidão negativa do condomínio", detail: "Obrigatório para imóveis em condomínio." },
      { id: "property.utilities", title: "Últimas contas de consumo quitadas", detail: "Água, luz e gás." },
      { id: "property.finance", title: "Último boleto de evolução do financiamento", detail: "Quando o imóvel possuir saldo devedor atual." }
    ]
  }
];

export const propertyGroups: FormGroup[] = [{
  id: "property-data",
  title: "Dados cadastrais",
  fields: [
    { key: "property.ref", label: "Referência no sistema", required: true },
    { key: "property.value", label: "Valor do imóvel", type: "currency", required: true },
    { key: "property.address", label: "Endereço", required: true, wide: true },
    { key: "property.neighborhood", label: "Bairro / condomínio" },
    { key: "property.registry", label: "Matrícula nº" },
    { key: "property.municipal", label: "Cadastro municipal" },
    { key: "property.origin", label: "Mídia / origem" },
    { key: "property.broker", label: "Corretor" },
    { key: "property.capturer", label: "Captador" },
    { key: "property.partnership", label: "Parceria" },
    { key: "property.contact", label: "Forma de contato" }
  ]
}];

function personFields(prefix: string, required: boolean): FormField[] {
  return [
    { key: `${prefix}.name`, label: "Nome completo", required, wide: true },
    { key: `${prefix}.rg`, label: "RG" },
    { key: `${prefix}.cpf`, label: "CPF/MF", required },
    { key: `${prefix}.nationality`, label: "Nacionalidade" },
    { key: `${prefix}.civilStatus`, label: "Estado civil", type: "select", options: [
      { value: "", label: "Selecione" }, { value: "solteiro", label: "Solteiro(a)" }, { value: "casado", label: "Casado(a)" },
      { value: "uniao_estavel", label: "União estável" }, { value: "divorciado", label: "Divorciado(a)" }, { value: "viuvo", label: "Viúvo(a)" }
    ] },
    { key: `${prefix}.profession`, label: "Profissão" },
    { key: `${prefix}.address`, label: "Endereço residencial", wide: true },
    { key: `${prefix}.neighborhood`, label: "Bairro" },
    { key: `${prefix}.city`, label: "Cidade / UF" },
    { key: `${prefix}.phones`, label: "Telefones", type: "tel" },
    { key: `${prefix}.email`, label: "E-mail", type: "email", required: prefix === "buyer" },
    { key: `${prefix}.bank`, label: "Banco" },
    { key: `${prefix}.agency`, label: "Agência" },
    { key: `${prefix}.account`, label: "Conta" },
    { key: `${prefix}.pix`, label: "PIX" },
    { key: `${prefix}.accountType`, label: "Tipo de conta", type: "select", options: [
      { value: "", label: "Selecione" }, { value: "corrente", label: "Corrente" }, { value: "poupanca", label: "Poupança" }
    ] }
  ];
}

export const peopleGroups: FormGroup[] = [
  { id: "buyer", title: "Comprador(a)", fields: personFields("buyer", true) },
  { id: "coBuyer", title: "Cônjuge ou sócio co-comprador", description: "Ative quando houver outra parte compradora.", enabledBy: "flags.coBuyer", fields: personFields("coBuyer", false) },
  { id: "seller", title: "Vendedor(a)", fields: personFields("seller", true) },
  { id: "coSeller", title: "Cônjuge ou sócio co-vendedor", description: "Ative quando houver outra parte vendedora.", enabledBy: "flags.coSeller", fields: personFields("coSeller", false) }
];

export const dealGroups: FormGroup[] = [
  {
    id: "terms",
    title: "Alinhamento do negócio",
    fields: [
      { key: "deal.totalValue", label: "Valor total da venda", type: "currency", required: true },
      { key: "deal.registryValue", label: "Valor para cartório", type: "currency" },
      { key: "deal.depositValue", label: "Valor do sinal (entrada)", type: "currency" },
      { key: "deal.depositDate", label: "Data / quando (sinal)", type: "date" },
      { key: "deal.depositMethod", label: "Forma de pagamento (sinal)", type: "select", options: paymentOptions },
      { key: "deal.installmentValue", label: "Intermediárias / reforços", type: "currency" },
      { key: "deal.installmentDate", label: "Data / quando (intermediária)", type: "date" },
      { key: "deal.installmentMethod", label: "Forma de pagamento (intermediária)", type: "select", options: paymentOptions },
      { key: "deal.financedValue", label: "Valor financiado", type: "currency" },
      { key: "deal.bank", label: "Banco / correspondente" }
    ]
  },
  {
    id: "commission",
    title: "Comissão",
    fields: [
      { key: "deal.commissionValue", label: "Valor da comissão", type: "currency" },
      { key: "deal.commissionPercent", label: "Percentual", type: "number", placeholder: "%" },
      { key: "deal.invoice", label: "Emissão de nota fiscal?", type: "select", options: yesNo },
      { key: "deal.commissionMethod", label: "Forma de pagamento", type: "select", options: paymentOptions.filter((item) => item.value !== "cheque_administrativo") },
      { key: "deal.payer", label: "Responsável pelo pagamento", type: "select", options: [
        { value: "", label: "Selecione" }, { value: "seller", label: "Vendedor" }, { value: "buyer", label: "Comprador" }
      ] },
      { key: "deal.recipient", label: "Destinatário", type: "select", options: [
        { value: "", label: "Selecione" }, { value: "visao", label: "Exclusivo Visão" }, { value: "split", label: "Dividido" }
      ] },
      { key: "deal.commissionDate", label: "Quando será paga", type: "date" }
    ]
  },
  {
    id: "possession",
    title: "Situação e posse",
    fields: [
      { key: "deal.occupancy", label: "Situação do imóvel", type: "select", options: [
        { value: "", label: "Selecione" }, { value: "owner", label: "Proprietário" }, { value: "tenant", label: "Inquilino" }, { value: "vacant", label: "Vago" }
      ] },
      { key: "deal.furniture", label: "Incluso mobília?", type: "select", options: yesNo },
      { key: "deal.possessionDate", label: "Data da entrega da posse", type: "date" }
    ]
  },
  {
    id: "partner",
    title: "Parceria externa",
    description: "Ative somente quando houver parceiro externo.",
    enabledBy: "flags.externalPartner",
    fields: [
      { key: "partner.name", label: "Nome do parceiro", wide: true },
      { key: "partner.creci", label: "CRECI" },
      { key: "partner.document", label: "CPF / CNPJ" },
      { key: "partner.phone", label: "Telefone", type: "tel" },
      { key: "partner.email", label: "E-mail", type: "email" },
      { key: "partner.bank", label: "Dados bancários / PIX", wide: true }
    ]
  },
  {
    id: "notes",
    title: "Informações complementares e observações",
    fields: [{ key: "deal.notes", label: "Observações", type: "textarea", wide: true, placeholder: "Registre condições, exceções e orientações relevantes para o contrato." }]
  }
];

export const legalRecipients = [
  "adriana.larangeira@visaoimoveis.imb.br",
  "tiago.amadio@gmail.com",
  "dany.corral@visaoimoveis.imb.br"
];

export function emptyPayload(): import("./types").FormPayload {
  const checklist: Record<string, import("./types").ChecklistEntry> = Object.fromEntries(checklistGroups.flatMap((group) => group.documents.map((document) => [
    document.id,
    { status: "pending" as const, notes: "", files: [] }
  ])));
  return {
    version: 1,
    values: { "meta.date": new Date().toISOString().slice(0, 10), "meta.city": "Indaiatuba" },
    checklist
  };
}
