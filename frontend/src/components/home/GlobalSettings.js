import React, { useState } from 'react';
import { HOPPER_COLORS } from '../../utils/colors';

export default function GlobalSettings({
  globalSettings,
  setGlobalSettings,
  updateGlobalSettings,
  newWord,
  setNewWord,
  wordbankExpanded,
  setWordbankExpanded,
  addWordToWordbank,
  removeWordFromWordbank,
  clearWordbank,
  showGlobalSettings,
  setShowGlobalSettings
}) {
  return (
    <div className="card">
      <button 
        className="global-settings-button"
        onClick={() => setShowGlobalSettings(!showGlobalSettings)}
        type="button"
      >
        ⚙️ Global Settings {showGlobalSettings ? '▼' : '▶'}
      </button>
      {showGlobalSettings && (
        <div className="settings-panel">
          <div className="setting-group">
            <label>
              Video Title Template <span className="char-counter">{globalSettings.title_template.length}/100</span>
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Use {'{filename}'} for filename, {'{random}'} for random wordbank word</span>
              </span>
            </label>
            <input 
              type="text"
              value={globalSettings.title_template}
              onChange={(e) => setGlobalSettings({...globalSettings, title_template: e.target.value})}
              onBlur={(e) => updateGlobalSettings('title_template', e.target.value)}
              placeholder="{filename}"
              className="input-text"
              maxLength="100"
            />
          </div>

          <div className="setting-group">
            <label>
              Video Description Template
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Use {'{filename}'} for filename, {'{random}'} for random wordbank word</span>
              </span>
            </label>
            <textarea 
              value={globalSettings.description_template}
              onChange={(e) => setGlobalSettings({...globalSettings, description_template: e.target.value})}
              onBlur={(e) => updateGlobalSettings('description_template', e.target.value)}
              placeholder="Uploaded via hopper"
              className="textarea-text"
              rows="3"
            />
          </div>

          <div className="setting-divider"></div>

          <div className="setting-group">
            <div className="wordbank-label">
              <div className="wordbank-title">
                <span>
                  Random Wordbank ({globalSettings.wordbank.length} words)
                  <span className="tooltip-wrapper">
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">Words to use with {'{random}'} placeholder. Enter comma-separated words to add multiple at once</span>
                  </span>
                </span>
                {globalSettings.wordbank.length > 0 && (
                  <span 
                    className={`wordbank-caret ${wordbankExpanded ? 'expanded' : ''}`}
                    onClick={() => setWordbankExpanded(!wordbankExpanded)}
                    title={wordbankExpanded ? 'Hide words' : 'Show words'}
                  >
                    ▼
                  </span>
                )}
              </div>
              {globalSettings.wordbank.length > 0 && (
                <button 
                  onClick={(e) => {
                    e.stopPropagation();
                    clearWordbank();
                  }}
                  className="btn-clear-wordbank"
                  title="Clear all words"
                >
                  Clear All
                </button>
              )}
            </div>
            <div className="wordbank-input">
              <input 
                type="text"
                value={newWord}
                onChange={(e) => setNewWord(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && newWord.trim() && addWordToWordbank(newWord.trim())}
                placeholder="Add word(s) - comma-separated for multiple"
                className="input-text"
              />
              <button 
                onClick={() => newWord.trim() && addWordToWordbank(newWord.trim())}
                className="btn-add-word"
                disabled={!newWord.trim()}
              >
                Add
              </button>
            </div>
            
            {globalSettings.wordbank.length > 0 && wordbankExpanded && (
              <div className="wordbank-list">
                {globalSettings.wordbank.map((word, idx) => (
                  <div key={idx} className="wordbank-item">
                    <span>{word}</span>
                    <button onClick={() => removeWordFromWordbank(word)} className="btn-remove-word">×</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="setting-divider"></div>

          <div className="setting-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                checked={globalSettings.upload_immediately}
                onChange={(e) => updateGlobalSettings('upload_immediately', e.target.checked)}
                className="checkbox"
              />
              <span>
                Upload Immediately
                <span className="tooltip-wrapper" style={{ marginLeft: '6px' }}>
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">If disabled, videos will be scheduled</span>
                </span>
              </span>
            </label>
          </div>

          {!globalSettings.upload_immediately && (
            <>
              <div className="setting-group">
                <label>Schedule Mode</label>
                <select 
                  value={globalSettings.schedule_mode}
                  onChange={(e) => updateGlobalSettings('schedule_mode', e.target.value)}
                  className="select"
                >
                  <option value="spaced">Spaced Interval</option>
                  <option value="specific_time">Specific Time</option>
                </select>
              </div>

              {globalSettings.schedule_mode === 'spaced' ? (
                <div className="setting-group">
                  <label>
                    Upload Interval
                    <span className="tooltip-wrapper">
                      <span className="tooltip-icon">i</span>
                      <span className="tooltip-text">Videos upload one at a time with this interval</span>
                    </span>
                  </label>
                  <div className="interval-input">
                    <input 
                      type="number"
                      min="1"
                      value={globalSettings.schedule_interval_value || ''}
                      onChange={(e) => {
                        const val = e.target.value;
                        if (val === '' || val === '-') {
                          setGlobalSettings({...globalSettings, schedule_interval_value: null});
                        } else {
                          const numVal = parseInt(val);
                          if (!isNaN(numVal) && numVal >= 1) {
                            setGlobalSettings({...globalSettings, schedule_interval_value: numVal});
                          }
                        }
                      }}
                      onBlur={(e) => {
                        const val = parseInt(e.target.value) || 1;
                        setGlobalSettings({...globalSettings, schedule_interval_value: val});
                        updateGlobalSettings('schedule_interval_value', val);
                      }}
                      className="input-number"
                    />
                    <select 
                      value={globalSettings.schedule_interval_unit}
                      onChange={(e) => updateGlobalSettings('schedule_interval_unit', e.target.value)}
                      className="select-unit"
                    >
                      <option value="minutes">Minutes</option>
                      <option value="hours">Hours</option>
                      <option value="days">Days</option>
                    </select>
                  </div>
                </div>
              ) : (
                <div className="setting-group">
                  <label>
                    Start Time
                    <span className="tooltip-wrapper">
                      <span className="tooltip-icon">i</span>
                      <span className="tooltip-text">All videos will upload at this time</span>
                    </span>
                  </label>
                  <input 
                    type="datetime-local"
                    value={globalSettings.schedule_start_time}
                    onChange={(e) => updateGlobalSettings('schedule_start_time', e.target.value)}
                    className="input"
                  />
                </div>
              )}

              {globalSettings.schedule_mode === 'spaced' && (
                <div className="setting-group">
                  <label className="checkbox-label">
                    <input 
                      type="checkbox"
                      checked={globalSettings.upload_first_immediately !== false}
                      onChange={(e) => updateGlobalSettings('upload_first_immediately', e.target.checked)}
                      className="checkbox"
                    />
                    <span>
                      Upload first video immediately
                      <span className="tooltip-wrapper" style={{ marginLeft: '6px' }}>
                        <span className="tooltip-icon">i</span>
                        <span className="tooltip-text">
                          When checked, the first video uploads immediately and subsequent videos are spaced by the interval.
                          When unchecked, all videos (including the first) are spaced evenly by the interval.
                        </span>
                      </span>
                    </span>
                  </label>
                </div>
              )}
            </>
          )}

          <div className="setting-divider"></div>

          <div className="setting-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                checked={globalSettings.allow_duplicates}
                onChange={(e) => updateGlobalSettings('allow_duplicates', e.target.checked)}
                className="checkbox"
              />
              <span>
                Allow Duplicate Videos
                <span className="tooltip-wrapper" style={{ marginLeft: '6px' }}>
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Allow uploading videos with the same filename</span>
                </span>
              </span>
            </label>
          </div>
        </div>
      )}
    </div>
  );
}

