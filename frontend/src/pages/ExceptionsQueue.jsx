import React, { useState, useEffect } from 'react';
import { AlertCircle, FileSpreadsheet, CheckCircle2, ChevronRight, Save, RefreshCw } from 'lucide-react';
import './ExceptionsQueue.css';

const ExceptionsQueue = () => {
  const [exceptions, setExceptions] = useState([]);
  const [selectedExceptionId, setSelectedExceptionId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState(false);
  
  // Single Mapping State for all dynamic fields
  const [newMapping, setNewMapping] = useState({});

  const fetchExceptions = async () => {
    try {
      const res = await fetch('/api/exceptions');
      const data = await res.json();
      setExceptions(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchExceptions();
    // Poll every 3 seconds for new interrupts
    const interval = setInterval(fetchExceptions, 3000);
    return () => clearInterval(interval);
  }, []);

  // Sync selected exception and initialize mappings
  useEffect(() => {
    if (exceptions.length > 0) {
      if (!selectedExceptionId || !exceptions.find(e => e.id === selectedExceptionId)) {
        const first = exceptions[0];
        setSelectedExceptionId(first.id);
        setNewMapping(first.mappedSchema.mapping || {});
      }
    } else {
      setSelectedExceptionId(null);
    }
  }, [exceptions, selectedExceptionId]);

  const selectedException = exceptions.find(e => e.id === selectedExceptionId);

  const handleResolve = async () => {
    if (!selectedException) return;
    setResolving(true);
    try {
      const updatedMapping = { 
        ...selectedException.mappedSchema, 
        mapping: newMapping
      };
      
      const res = await fetch('/api/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          thread_id: selectedException.id,
          new_mapping: updatedMapping
        })
      });
      if (res.ok) {
        // Optimistically remove it from the list
        const remaining = exceptions.filter(e => e.id !== selectedException.id);
        setExceptions(remaining);
      }
    } catch (err) {
      console.error(err);
      alert('Failed to resolve exception.');
    }
    setResolving(false);
  };

  const updateMappingField = (canonicalField, rawColumn) => {
    setNewMapping(prev => ({
      ...prev,
      [canonicalField]: rawColumn
    }));
  };

  return (
    <div className="queue-container">
      <div className="queue-header flex justify-between items-center">
        <div>
          <h1 className="text-h1">Exceptions Queue</h1>
          <p className="text-muted">Human-in-the-Loop verification for LangGraph interrupted states.</p>
        </div>
        <button className="btn btn-secondary" onClick={fetchExceptions}>
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      <div className="queue-layout">
        {/* Left Side: List of Exceptions */}
        <div className="exceptions-list card">
          <div className="card-header">
            <h3 className="text-h3 font-semibold">Active Interrupts</h3>
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
                  onClick={() => {
                    setSelectedExceptionId(exc.id);
                    setNewMapping(exc.mappedSchema.mapping || {});
                  }}
                >
                  <div className="item-icon">
                    <AlertCircle size={20} className="text-danger" />
                  </div>
                  <div className="item-details">
                    <span className="file-name">{exc.fileName}</span>
                    <span className="error-type">{exc.type}</span>
                    <span className="time">{exc.timestamp}</span>
                  </div>
                  <ChevronRight size={18} className="text-muted" />
                </div>
              ))
            ) : (
              <div className="empty-state">
                <CheckCircle2 size={40} className="text-success mb-4" />
                <h3 className="text-h3">All caught up!</h3>
                <p className="text-muted">No pending interruptions in the LangGraph state machine.</p>
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Exception Resolution UI */}
        {selectedException && (
          <div className="resolution-panel card">
            <div className="panel-header">
              <div className="flex items-center gap-2">
                <FileSpreadsheet size={20} className="text-accent" />
                <h2 className="text-h2">Review Mapping</h2>
              </div>
              <span className="badge badge-warning">Action Required</span>
            </div>
            
            <div className="panel-body">
              <div className="error-banner">
                <AlertCircle size={20} />
                <p>{selectedException.message}</p>
              </div>

              <div className="mapping-editor">
                <h3 className="text-h3 mb-4">Schema Mapping Adjustments</h3>
                <p className="text-muted mb-6">The deterministic invariant probe halted the pipeline. Adjust the column mappings below to resolve the mathematical discrepancy.</p>
                
                {Object.entries(newMapping).map(([canonicalField, rawColumn]) => (
                  <div className="form-group" key={canonicalField}>
                    <label className="capitalize">{canonicalField.replace(/_/g, ' ')} Column</label>
                    <select 
                      value={rawColumn} 
                      onChange={(e) => updateMappingField(canonicalField, e.target.value)}
                      className={canonicalField.includes('fee') ? 'highlighted-field' : ''}
                    >
                      <option value="" disabled>Select a column...</option>
                      {selectedException.availableColumns && selectedException.availableColumns.map(col => (
                         <option key={col} value={col}>{col}</option>
                      ))}
                      <option value="ignore">-- Map to Zero --</option>
                    </select>
                    {canonicalField.includes('fee') && (
                      <span className="field-hint text-danger">The mathematical error commonly originates here.</span>
                    )}
                  </div>
                ))}

              </div>
            </div>

            <div className="panel-footer">
              <button className="btn btn-secondary">Ignore & Drop File</button>
              <button className="btn btn-primary" onClick={handleResolve} disabled={resolving}>
                <Save size={16} />
                {resolving ? 'Submitting...' : 'Submit & Resume Pipeline'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ExceptionsQueue;
