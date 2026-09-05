import React, { useState } from 'react';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, 
  LineChart, Line 
} from 'recharts';
import { ArrowUpRight, ArrowDownRight, DollarSign, FileCheck, AlertTriangle, UploadCloud } from 'lucide-react';
import './Dashboard.css';

// Remove mockData

const StatCard = ({ title, value, change, isPositive, icon: Icon }) => (
  <div className="stat-card">
    <div className="stat-header">
      <span className="stat-title">{title}</span>
      <div className="stat-icon-wrapper">
        <Icon size={18} />
      </div>
    </div>
    <div className="stat-value">{value}</div>
    <div className={`stat-change ${isPositive ? 'positive' : 'negative'}`}>
      {isPositive ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
      <span>{change} from last month</span>
    </div>
  </div>
);

const Dashboard = () => {
  const [uploading, setUploading] = useState(null);
  const [stats, setStats] = useState({
    totalReconciledValue: 0,
    autoMatchRate: 0,
    pendingExceptions: 0,
    matchData: [],
    trendData: []
  });

  React.useEffect(() => {
    fetch('/api/stats/dashboard')
      .then(r => r.json())
      .then(data => {
        if (!data.status) {
          setStats(data);
        }
      })
      .catch(console.error);
  }, []);

  const handleReset = async () => {
    try {
      const res = await fetch('/api/reset', { method: 'POST' });
      if (res.ok) alert('Database wiped and Idempotency reset. You can now re-upload files.');
    } catch (e) {
      alert('Failed to reset DB');
    }
  };

  const simulateUpload = async (fileName, hint) => {
    setUploading(fileName);
    try {
      // Fetch the bundled synthetic file from the public folder (busting cache so it always gets the latest generated file)
      const response = await fetch(`/demo_files/${fileName}?v=${Date.now()}`);
      const blob = await response.blob();
      
      const formData = new FormData();
      formData.append('file', blob, fileName);
      formData.append('source_hint', hint);

      // Post to FastAPI backend
      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });
      
      const data = await res.json();
      console.log('Upload response:', data);
      
      if(data.status === 'processing') {
        alert(`${fileName} ingested successfully. Pipeline started!`);
      }
    } catch (err) {
      console.error(err);
      alert('Failed to upload file.');
    }
    setUploading(null);
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="text-h1">Reconciliation Overview</h1>
        <p className="text-muted">Real-time matching engine performance across all payment gateways.</p>
      </div>

      <div className="stats-grid">
        <StatCard 
          title="Total Reconciled Value" 
          value={`$${stats.totalReconciledValue > 1000000 ? (stats.totalReconciledValue / 1000000).toFixed(1) + 'M' : stats.totalReconciledValue.toLocaleString()}`} 
          change="+14.2%" 
          isPositive={true}
          icon={DollarSign}
        />
        <StatCard 
          title="Auto-Match Rate" 
          value={`${stats.autoMatchRate.toFixed(1)}%`} 
          change="+2.1%" 
          isPositive={true}
          icon={FileCheck}
        />
        <StatCard 
          title="Pending Exceptions" 
          value={stats.pendingExceptions.toString()} 
          change="-12.5%" 
          isPositive={true}
          icon={AlertTriangle}
        />
      </div>

      <div className="upload-section card">
        <div className="card-header flex justify-between items-center">
          <h3 className="text-h3 font-semibold">Demo Ingestion Sources</h3>
          <button className="btn btn-secondary text-danger border-danger" onClick={handleReset}>
             Reset Database (Clear State)
          </button>
        </div>
        <div className="upload-actions">
          <button 
            className="btn btn-secondary upload-btn" 
            onClick={() => simulateUpload('erp_export.csv', 'ERP Export')}
            disabled={uploading !== null}
          >
            <UploadCloud size={18} className="text-accent" />
            {uploading === 'erp_export.csv' ? 'Ingesting...' : 'Ingest ERP Export'}
          </button>
          
          <button 
            className="btn btn-secondary upload-btn" 
            onClick={() => simulateUpload('razorpay_recon.csv', 'Razorpay Settlement')}
            disabled={uploading !== null}
          >
            <UploadCloud size={18} className="text-accent" />
            {uploading === 'razorpay_recon.csv' ? 'Ingesting...' : 'Ingest Razorpay Recon'}
          </button>
          
          <button 
            className="btn btn-secondary upload-btn" 
            onClick={() => simulateUpload('bank_statement.csv', 'Bank Statement')}
            disabled={uploading !== null}
          >
            <UploadCloud size={18} className="text-accent" />
            {uploading === 'bank_statement.csv' ? 'Ingesting...' : 'Ingest Bank Statement'}
          </button>
        </div>
        
        <div className="mt-6 flex justify-end border-t border-white/10 pt-4" style={{gap: '1rem'}}>
          <button 
            className="btn btn-secondary"
            onClick={() => {
              window.open('/api/reports/allocations/csv', '_blank');
            }}
          >
            Download Audit CSV
          </button>
          <button 
            className="btn btn-primary"
            onClick={async () => {
              try {
                const res = await fetch('/api/reconcile/solve', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success') {
                  const stats = data.stats;
                  alert(`Reconciliation Engine Complete!\n\nMatches: ${stats.total_allocated_pairs}\nOrphans Swept: ${stats.mature_orphans_swept}\nLatency: ${stats.total_time_ms}ms\n\nPlease check the AI Forensic Queue for exceptions.`);
                } else {
                  alert('Reconciliation failed: ' + data.message);
                }
              } catch (err) {
                alert('Error running reconciliation engine');
              }
            }}
          >
            Run Auto-Reconciliation Engine
          </button>
        </div>
      </div>

      <div className="charts-grid">
        <div className="chart-card">
          <h3 className="text-h3 mb-6">Daily Match vs Exceptions</h3>
          <div className="chart-wrapper">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stats.matchData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 12}} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 12}} dx={-10} />
                <Tooltip cursor={{fill: '#f8fafc'}} />
                <Bar dataKey="matched" stackId="a" fill="var(--color-primary)" radius={[0, 0, 4, 4]} />
                <Bar dataKey="exception" stackId="a" fill="var(--color-danger)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="chart-card">
          <h3 className="text-h3 mb-6">Intraday Processing Volume</h3>
          <div className="chart-wrapper">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={stats.trendData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 12}} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 12}} dx={-10} />
                <Tooltip />
                <Line type="monotone" dataKey="volume" stroke="var(--color-accent)" strokeWidth={3} dot={{r: 4, strokeWidth: 2}} activeDot={{r: 6}} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
