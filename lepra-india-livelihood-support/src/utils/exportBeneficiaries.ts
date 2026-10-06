import { Beneficiary } from '../types';

const COLUMNS: Array<{ header: string; key: string; width?: number }> = [
  { header: 'Beneficiary ID', key: 'id', width: 16 },
  { header: 'Type', key: 'type', width: 12 },
  { header: 'Name', key: 'name', width: 22 },
  { header: 'Group Name', key: 'groupName', width: 18 },
  { header: 'Contact Number', key: 'contactNumber', width: 16 },
  { header: 'Gender', key: 'gender', width: 10 },
  { header: 'Age', key: 'age', width: 8 },
  { header: 'District', key: 'district', width: 16 },
  { header: 'State', key: 'state', width: 16 },
  { header: 'Project Name', key: 'projectName', width: 26 },
  { header: 'Funding Partner', key: 'fundingPartner', width: 18 },
  { header: 'Welfare-Only Beneficiary', key: 'isWelfareOnly', width: 18 },
  { header: 'Disease Type', key: 'diseaseType', width: 14 },
  { header: 'Treatment Status', key: 'treatmentStatus', width: 16 },
  { header: 'Business Name', key: 'businessName', width: 22 },
  { header: 'Business Sector', key: 'businessSector', width: 16 },
  { header: 'Status', key: 'status', width: 20 },
  { header: 'Requested Amount (INR)', key: 'requestedAmount', width: 18 },
  { header: 'Approved Amount (INR)', key: 'approvedAmount', width: 18 },
  { header: 'Repayment Term (Months)', key: 'repaymentTermMonths', width: 18 },
  { header: 'Monthly EMI (INR)', key: 'monthlyRepaymentEMI', width: 16 },
  { header: 'Total Recovered (INR)', key: 'totalRecovered', width: 18 },
  { header: 'Outstanding Balance (INR)', key: 'outstandingBalance', width: 20 },
  { header: 'Approval Date', key: 'approvalDate', width: 14 },
  { header: 'Disbursement Date', key: 'disbursementDate', width: 16 },
  { header: 'Verification Completed', key: 'verificationCompleted', width: 18 },
  { header: 'Registered By Agent', key: 'registeredByAgent', width: 20 },
  { header: 'Registered At', key: 'registeredAt', width: 20 },
  { header: 'Rejection Reason', key: 'rejectionReason', width: 24 }
];

function toRow(b: Beneficiary) {
  const totalRecovered = (b.payments || []).reduce((sum, p) => sum + p.amount, 0);
  const outstandingBalance = (b.approvedAmount || 0) - totalRecovered;
  return {
    id: b.id,
    type: b.type,
    name: b.name,
    groupName: b.groupName || '',
    contactNumber: b.contactNumber,
    gender: b.gender,
    age: b.age,
    district: b.district,
    state: b.state,
    projectName: b.projectName || '',
    fundingPartner: b.fundingPartner || '',
    isWelfareOnly: b.isWelfareOnly ? 'Yes' : 'No',
    diseaseType: b.diseaseType,
    treatmentStatus: b.treatmentStatus,
    businessName: b.businessName,
    businessSector: b.businessSector,
    status: b.status,
    requestedAmount: b.requestedAmount || 0,
    approvedAmount: b.approvedAmount || 0,
    repaymentTermMonths: b.repaymentTermMonths || '',
    monthlyRepaymentEMI: b.monthlyRepaymentEMI || '',
    totalRecovered,
    outstandingBalance,
    approvalDate: b.approvalDate || '',
    disbursementDate: b.disbursementDate || '',
    verificationCompleted: b.verification?.isCompleted ? 'Yes' : 'No',
    registeredByAgent: b.registeredByAgent,
    registeredAt: b.registeredAt,
    rejectionReason: b.rejectionReason || ''
  };
}





export async function exportBeneficiariesToExcel(beneficiaries: Beneficiary[]): Promise<void> {
  const { Workbook } = await import('exceljs');
  const workbook = new Workbook();
  workbook.creator = 'LEPRA Society Livelihood Support System';
  workbook.created = new Date();

  const sheet = workbook.addWorksheet('Beneficiaries');
  sheet.columns = COLUMNS;
  sheet.getRow(1).font = { bold: true };
  sheet.getRow(1).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF102C57' } };
  sheet.getRow(1).font = { bold: true, color: { argb: 'FFFFFFFF' } };

  beneficiaries.forEach((b) => sheet.addRow(toRow(b)));

  const buffer = await workbook.xlsx.writeBuffer();
  const blob = new Blob([buffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  });

  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  const dateStamp = new Date().toISOString().slice(0, 10);
  link.href = url;
  link.download = `LEPRA_Beneficiaries_${dateStamp}.xlsx`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
