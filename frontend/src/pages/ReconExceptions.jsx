import React, { useState, useEffect, useRef } from 'react';
import { AlertTriangle, Activity, Database, CheckCircle2, FileSpreadsheet, XCircle, FileWarning } from 'lucide-react';
import './ReconExceptions.css';

const ReconExceptions = () => {
  const [exceptions, setExceptions] = useState([]);
  const [selectedException, setSelectedException] = useState(null);
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState(false);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState([]);
  const [selectedTargetIds, setSelectedTargetIds] = useState([]);
  const adjustmentRef = useRef(null);

  useEffect(() => {
    setSelectedCandidateIds([]);
    setSelectedTargetIds([]);
    if (adjustmentRef.current) adjustmentRef.current.value = "";
  }, [selectedException?.id]);

  const fetchExceptions = async () => {
    try {
      const res = await fetch('/api/recon/exceptions');
      if (res.ok) {
        const data = await res.json();
        setExceptions(data);
      }
    } catch (err) {
      console.error("Failed to fetch recon exceptions:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchExceptions();
    const interval = setInterval(fetchExceptions, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (exceptions.length > 0) {
      if (!selectedException) {
        setSelectedException(exceptions[0]);
      } else {
        // Keep selectedException pointing to the updated data if it still exists
        const updated = exceptions.find(e => e.id === selectedException.id);
        if (updated) {
          setSelectedException(updated);
        } else {
          setSelectedException(exceptions[0]);
        }
      }
    } else {
      setSelectedException(null);
    }
  }, [exceptions]);

  const handleResolve = async (action) => {
    if (!selectedException) return;
    setResolving(true);
    try {
      const adjustment = adjustmentRef.current ? parseFloat(adjustmentRef.current.value) || 0 : 0;
      const payload = {
        action,
        candidate_ids: selectedCandidateIds,
        target_ids: selectedTargetIds,
        adjustment
      };
      const res = await fetch(`/api/recon/exceptions/${selectedException.id}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'resolved' || data.status === 'not_found' || data.status === 'success') {
          setExceptions(prev => prev.filter(e => e.id !== selectedException.id));
        } else {
          // Partial resolve
          setSelectedCandidateIds([]);
          setSelectedTargetIds([]);
          if (adjustmentRef.current) adjustmentRef.current.value = "";
          fetchExceptions();
        }
      } else {
        alert('Failed to resolve exception.');
      }
    } catch (err) {
      console.error(err);
      alert('Failed to resolve exception.');
    }
    setResolving(false);
  };

  const getClassificationBadge = (classification) => {
    switch(classification) {
      case 'AMOUNT_VARIANCE': return <span className="badge badge-warning">Amount Variance</span>;
      case 'DATA_QUALITY_ERROR': return <span className="badge badge-danger">Data Quality Error</span>;
      default: return <span className="badge badge-secondary">{classification}</span>;
    }
  };

  const handleToggleCandidate = (id) => {
    setSelectedCandidateIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const handleToggleTarget = (id) => {
    setSelectedTargetIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  return (
    <div className="recon-container">
      <div className="queue-header flex justify-between items-center mb-6">
        <div>
          <h1 className="text-h1">AI Forensic Queue</h1>
          <p className="text-muted">Manually resolve mathematically broken or orphaned clusters.</p>
        </div>
      </div>

      <div className="recon-layout">
        {/* Left Side: Exception List */}
        <div className="card list-panel">
          <div className="card-header">
            <h3 className="text-h3 font-semibold">Pending Investigations</h3>
            <span className="badge badge-danger">{exceptions.length}</span>
          </div>
          <div className="list-content">
            {loading ? (
              <div className="empty-state"><p className="text-muted">Loading...</p></div>
            ) : exceptions.length > 0 ? (
              exceptions.map(exc => (
                <div 
                  key={exc.id}
                  className={`exception-item ${selectedException?.id === exc.id ? 'active' : ''}`}
                  onClick={() => setSelectedException(exc)}
                >
                  <div className="item-icon">
                    <Activity size={20} className="text-accent" />
                  </div>
                  <div className="item-details">
                    <span className="file-name text-sm font-mono truncate">{exc.cluster_id}</span>
                    <span className="error-type text-xs text-muted">Reason: {exc.reason}</span>
                    <div className="mt-1">
                      {getClassificationBadge(exc.investigation_result?.classification)}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">
                <CheckCircle2 size={40} className="text-success mb-4" />
                <h3 className="text-h3">Zero Exceptions</h3>
                <p className="text-muted">All clusters have been deterministically resolved.</p>
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Side-by-Side Review */}
        {selectedException && (
          <div className="review-panel flex flex-col gap-4">
            
            {/* AI Hypothesis Card */}
            <div className="card ai-hypothesis-card">
              <div className="card-header border-b border-white/5 pb-3">
                <h3 className="text-h3 font-semibold text-accent flex items-center gap-2">
                  <AlertTriangle size={18} />
                  AI Forensic Autopsy
                </h3>
                {getClassificationBadge(selectedException.investigation_result?.classification)}
              </div>
              <div className="card-body pt-4">
                <p className="text-body text-gray-300 leading-relaxed text-sm">
                  {selectedException.investigation_result?.hypothesis || "No AI hypothesis generated."}
                </p>
              </div>
            </div>

            {/* Split Pane: Target vs Candidates */}
            <div className="split-pane">
              {(() => {
                const allNodes = selectedException.cluster_data?.nodes || [];
                
                const hasBankTarget = allNodes.some(n => {
                  const data = typeof n === 'object' && !Array.isArray(n) ? n : n[1];
                  return data.type === 'BANK_SETTLEMENT_EVENT';
                });
                const hasPgPayout = allNodes.some(n => {
                  const data = typeof n === 'object' && !Array.isArray(n) ? n : n[1];
                  return data.type === 'PG_PAYOUT_EVENT';
                });
                
                let targetType = 'BANK_SETTLEMENT_EVENT';
                if (!hasBankTarget) {
                  if (hasPgPayout) targetType = 'PG_PAYOUT_EVENT';
                  else targetType = 'PG_PAYMENT_EVENT'; // Fallback for ERP vs PG
                }
                
                const targetNodes = allNodes.filter(n => {
                  const data = typeof n === 'object' && !Array.isArray(n) ? n : n[1];
                  return data.type === targetType;
                });
                const candidateNodes = allNodes.filter(n => {
                  const data = typeof n === 'object' && !Array.isArray(n) ? n : n[1];
                  return data.type !== targetType;
                });
                
                return (
                  <>
                    {/* Candidates */}
                    <div className="data-card border-t-blue">
                      <div className="card-header">
                        <h4 className="text-h4 font-medium flex" style={{alignItems: 'center', gap: '8px'}}><Database size={16}/> Candidate Source Events</h4>
                      </div>
                      <div className="card-body">
                        {candidateNodes.length > 0 ? (
                          candidateNodes.map(node => {
                            const id = typeof node === 'object' && !Array.isArray(node) ? node.id : node[0];
                            const data = typeof node === 'object' && !Array.isArray(node) ? node : node[1];
                            return (
                              <div key={id} className="data-row" style={{display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '1rem'}}>
                                <input type="checkbox" checked={selectedCandidateIds.includes(id)} onChange={() => handleToggleCandidate(id)} style={{width: '16px', height: '16px', cursor: 'pointer'}} />
                                <div style={{flex: 1}}>
                                  <div className="data-row-header">
                                    <span className="text-xs font-mono text-muted">ID: {id.split('-')[0]}</span>
                                    <span className="badge" style={{background: '#dbeafe', color: '#1e40af'}}>{data.type}</span>
                                  </div>
                                  <div className="data-row-body">
                                    <span className="text-sm text-main font-medium truncate" style={{maxWidth: '70%'}} title={data.description}>{data.description}</span>
                                    <span className="font-mono font-semibold" style={{color: '#0f172a'}}>${Number(data.amount).toFixed(2)}</span>
                                  </div>
                                </div>
                              </div>
                            )
                          })
                        ) : (
                          <div className="target-placeholder text-muted">
                            <FileWarning size={32} style={{marginBottom: '8px'}} />
                            <p>No Candidate Events</p>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Target */}
                    <div className="data-card border-t-purple">
                      <div className="card-header">
                        <h4 className="text-h4 font-medium flex" style={{alignItems: 'center', gap: '8px'}}><FileSpreadsheet size={16}/> Target Deposit Event</h4>
                      </div>
                      <div className="card-body" style={{...(targetNodes.length === 0 ? {display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'} : {})}}>
                          {targetNodes.length > 0 ? (
                            targetNodes.map(node => {
                              const id = typeof node === 'object' && !Array.isArray(node) ? node.id : node[0];
                              const data = typeof node === 'object' && !Array.isArray(node) ? node : node[1];
                              return (
                                <div key={id} className="data-row" style={{borderLeft: '4px solid #a855f7', display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '1rem'}}>
                                  <input type="checkbox" checked={selectedTargetIds.includes(id)} onChange={() => handleToggleTarget(id)} style={{width: '16px', height: '16px', cursor: 'pointer'}} />
                                  <div style={{flex: 1}}>
                                    <div className="data-row-header">
                                      <span className="text-xs font-mono text-muted">ID: {id.split('-')[0]}</span>
                                      <span className="badge" style={{background: '#f3e8ff', color: '#7e22ce'}}>{data.type}</span>
                                    </div>
                                    <div className="data-row-body">
                                      <span className="text-sm text-main font-medium truncate" style={{maxWidth: '70%'}} title={data.description}>{data.description}</span>
                                      <span className="font-mono font-semibold" style={{color: '#0f172a'}}>${Number(data.amount).toFixed(2)}</span>
                                    </div>
                                  </div>
                                </div>
                              )
                            })
                          ) : selectedException.reason === "ORPHANED" ? (
                            <div className="target-placeholder text-muted">
                              <XCircle size={32} style={{marginBottom: '8px', color: 'var(--color-danger)'}} />
                              <p>No matching deposit statement found.</p>
                            </div>
                          ) : (
                            <div className="target-placeholder">
                              <p style={{color: '#7e22ce', fontWeight: 500, marginBottom: '8px'}}>Reconciliation target requires a bank statement row.</p>
                              <p className="text-sm text-muted">Compare candidate totals against the expected settlement.</p>
                            </div>
                          )}
                      </div>
                    </div>
                  </>
                );
              })()}
            </div>

            {/* Resolution Action Bar */}
            <div className="action-bar">
              <div className="flex" style={{gap: '1rem', alignItems: 'center'}}>
                <span className="text-sm font-medium" style={{color: '#94a3b8'}}>Manual Adjustment:</span>
                <div className="adjustment-input">
                  <span>$</span>
                  <input type="number" placeholder="0.00" ref={adjustmentRef} />
                </div>
              </div>
              <div className="flex" style={{gap: '0.75rem'}}>
                <button 
                  className="btn btn-reject flex" style={{alignItems: 'center', gap: '8px'}}
                  onClick={() => handleResolve('reject')}
                  disabled={resolving}
                >
                  <XCircle size={16} /> Reject & Delete
                </button>
                <button 
                  className="btn btn-resolve flex" style={{alignItems: 'center', gap: '8px'}}
                  onClick={() => handleResolve('match')}
                  disabled={resolving}
                >
                  <CheckCircle2 size={16} /> Force Match & Clear
                </button>
              </div>
            </div>

          </div>
        )}
      </div>
    </div>
  );
};

export default ReconExceptions;
