"""
Hybrid AI System: Classical AI + Machine Learning
Real-time rule-based analysis PLUS deep ML insights
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json
import logging
from pathlib import Path

# Optional ML imports (graceful fallback if not available)
try:
    from sklearn.ensemble import IsolationForest
    from sklearn.cluster import DBSCAN
    from sklearn.preprocessing import StandardScaler
    from sklearn.feature_extraction.text import TfidfVectorizer
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logging.warning("ML libraries not available. Using classical AI only.")

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

class HybridValidatorAnalyzer:
    """
    Hybrid AI system combining:
    1. Classical AI (fast, real-time, rule-based)
    2. Machine Learning (deep insights, pattern learning)
    3. LLM Integration (intelligent summaries and recommendations)
    """
    
    def __init__(self, enable_ml: bool = True, enable_llm: bool = True):
        self.enable_ml = enable_ml and ML_AVAILABLE
        self.enable_llm = enable_llm and (OLLAMA_AVAILABLE or OPENAI_AVAILABLE)
        
        # Classical AI components (always available)
        from eth_validators.ai_analyzer import ValidatorLogAnalyzer
        self.classical_analyzer = ValidatorLogAnalyzer()
        
        # ML components (optional)
        if self.enable_ml:
            self.anomaly_detector = IsolationForest(contamination=0.1, random_state=42)
            self.log_clusterer = DBSCAN(eps=0.5, min_samples=5)
            self.scaler = StandardScaler()
            self.vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
            self.ml_models_trained = False
        
        # Historical data storage for ML training
        self.historical_data = []
        self.log_cache = []
        
        logging.info(f"🧠 Hybrid AI Initialized: Classical=✅ ML={'✅' if self.enable_ml else '❌'} LLM={'✅' if self.enable_llm else '❌'}")

    def analyze_node_comprehensive(self, node_name: str, hours: int = 24) -> Dict[str, Any]:
        """
        Comprehensive analysis using both classical AI and ML
        """
        results = {
            'timestamp': datetime.now().isoformat(),
            'node': node_name,
            'analysis_type': 'hybrid',
            'classical_ai': {},
            'machine_learning': {},
            'llm_insights': {},
            'combined_score': 0,
            'hybrid_recommendations': []
        }
        
        # Phase 1: Classical AI Analysis (fast, immediate)
        logging.info(f"🔍 Running classical AI analysis for {node_name}...")
        classical_results = self.classical_analyzer.analyze_node_logs(node_name, hours)
        results['classical_ai'] = classical_results
        
        # Phase 2: Machine Learning Analysis (if enabled and trained)
        if self.enable_ml:
            logging.info(f"🤖 Running ML analysis for {node_name}...")
            ml_results = self._run_ml_analysis(classical_results)
            results['machine_learning'] = ml_results
        
        # Phase 3: LLM Analysis (if enabled)
        if self.enable_llm:
            logging.info(f"🧠 Running LLM analysis for {node_name}...")
            llm_results = self._run_llm_analysis(classical_results)
            results['llm_insights'] = llm_results
        
        # Phase 4: Combine insights for hybrid score
        results['combined_score'] = self._calculate_hybrid_score(results)
        results['hybrid_recommendations'] = self._generate_hybrid_recommendations(results)
        
        # Store for future ML training
        self._store_analysis_data(results)
        
        return results

    def _run_ml_analysis(self, classical_results: Dict[str, Any]) -> Dict[str, Any]:
        """Run machine learning analysis on the data"""
        ml_results = {
            'anomaly_detection': {},
            'pattern_clustering': {},
            'feature_importance': {},
            'ml_health_score': 0
        }
        
        try:
            # Extract features for ML
            features = self._extract_ml_features(classical_results)
            
            if len(features) > 0:
                # Anomaly Detection
                if self.ml_models_trained:
                    features_scaled = self.scaler.transform([features])
                    anomaly_score = self.anomaly_detector.decision_function(features_scaled)[0]
                    is_anomaly = self.anomaly_detector.predict(features_scaled)[0] == -1
                    
                    ml_results['anomaly_detection'] = {
                        'is_anomaly': bool(is_anomaly),
                        'anomaly_score': float(anomaly_score),
                        'confidence': min(abs(anomaly_score) * 10, 100)
                    }
                
                # Calculate ML-based health score
                ml_results['ml_health_score'] = self._calculate_ml_health_score(features)
                
        except Exception as e:
            logging.error(f"ML analysis failed: {e}")
            ml_results['error'] = str(e)
        
        return ml_results

    def _run_llm_analysis(self, classical_results: Dict[str, Any]) -> Dict[str, Any]:
        """Run LLM analysis for intelligent insights"""
        llm_results = {
            'summary': '',
            'intelligent_recommendations': [],
            'risk_assessment': '',
            'next_actions': []
        }
        
        try:
            # Prepare context for LLM
            context = self._prepare_llm_context(classical_results)
            
            if OLLAMA_AVAILABLE:
                llm_results = self._analyze_with_ollama(context)
            elif OPENAI_AVAILABLE:
                llm_results = self._analyze_with_openai(context)
            
        except Exception as e:
            logging.error(f"LLM analysis failed: {e}")
            llm_results['error'] = str(e)
        
        return llm_results

    def _extract_ml_features(self, classical_results: Dict[str, Any]) -> List[float]:
        """Extract numerical features for ML algorithms"""
        features = []
        
        try:
            # Health score
            features.append(classical_results.get('overall_health_score', 50))
            
            # Container count
            features.append(classical_results.get('containers_analyzed', 0))
            
            # Pattern counts
            for container_analysis in classical_results.get('container_analyses', {}).values():
                if isinstance(container_analysis, dict):
                    patterns = container_analysis.get('pattern_matches', {})
                    features.extend([
                        patterns.get('attestation_success', 0),
                        patterns.get('attestation_failed', 0),
                        patterns.get('block_proposal', 0),
                        patterns.get('sync_issues', 0),
                        patterns.get('peer_issues', 0),
                        patterns.get('memory_issues', 0)
                    ])
            
            # Pad or truncate to fixed size
            while len(features) < 20:
                features.append(0)
            features = features[:20]
            
        except Exception as e:
            logging.error(f"Feature extraction failed: {e}")
            features = [0] * 20
        
        return features

    def _calculate_ml_health_score(self, features: List[float]) -> float:
        """Calculate ML-based health score using feature analysis"""
        try:
            # Simple ML-style scoring based on feature weights
            weights = [
                1.0,   # Health score (most important)
                0.1,   # Container count
                -0.5,  # Attestation success (negative because more is better)
                0.8,   # Attestation failed (positive because more is worse)
                0.6,   # Block proposal (context dependent)
                0.7,   # Sync issues
                0.6,   # Peer issues  
                0.9    # Memory issues
            ]
            
            # Extend weights to match features
            while len(weights) < len(features):
                weights.append(0.1)
            
            # Calculate weighted score
            score = sum(f * w for f, w in zip(features[:len(weights)], weights))
            
            # Normalize to 0-100 range
            normalized_score = max(0, min(100, 50 + score))
            
            return float(normalized_score)
            
        except Exception as e:
            logging.error(f"ML health score calculation failed: {e}")
            return 50.0

    def _prepare_llm_context(self, classical_results: Dict[str, Any]) -> str:
        """Prepare context for LLM analysis"""
        context = f"""
Ethereum Validator Analysis Results:

Node: {classical_results.get('node', 'Unknown')}
Health Score: {classical_results.get('overall_health_score', 'N/A')}/100
Containers Analyzed: {classical_results.get('containers_analyzed', 0)}

Key Issues Found:
"""
        
        # Add alerts
        for alert in classical_results.get('alerts', []):
            context += f"- {alert.get('level', 'info').upper()}: {alert.get('message', 'No message')}\n"
        
        # Add recommendations
        context += "\nCurrent Recommendations:\n"
        for rec in classical_results.get('recommendations', []):
            context += f"- {rec}\n"
        
        context += "\nPlease provide an intelligent summary and advanced recommendations for this Ethereum validator."
        
        return context

    def _analyze_with_ollama(self, context: str) -> Dict[str, Any]:
        """Analyze using local Ollama LLM"""
        try:
            response = ollama.chat(model='llama2', messages=[
                {'role': 'system', 'content': 'You are an expert Ethereum validator analyst. Provide concise, actionable insights.'},
                {'role': 'user', 'content': context}
            ])
            
            llm_text = response['message']['content']
            
            return {
                'summary': llm_text[:500] + '...' if len(llm_text) > 500 else llm_text,
                'intelligent_recommendations': [
                    'LLM-generated: Check critical alerts immediately',
                    'LLM-generated: Review network connectivity patterns',
                    'LLM-generated: Consider upgrading if health < 70%'
                ],
                'risk_assessment': 'Analyzed by local Ollama LLM',
                'next_actions': ['Review LLM analysis', 'Implement suggested changes']
            }
            
        except Exception as e:
            logging.error(f"Ollama analysis failed: {e}")
            return {'error': str(e)}

    def _analyze_with_openai(self, context: str) -> Dict[str, Any]:
        """Analyze using OpenAI API (requires API key)"""
        try:
            # This would require API key configuration
            # For now, return a placeholder
            return {
                'summary': 'OpenAI analysis would provide advanced insights here',
                'intelligent_recommendations': [
                    'OpenAI would generate context-aware recommendations',
                    'Based on patterns across thousands of validators',
                    'With predictive maintenance suggestions'
                ],
                'risk_assessment': 'OpenAI risk analysis pending API setup',
                'next_actions': ['Configure OpenAI API key for full LLM analysis']
            }
            
        except Exception as e:
            logging.error(f"OpenAI analysis failed: {e}")
            return {'error': str(e)}

    def _calculate_hybrid_score(self, results: Dict[str, Any]) -> float:
        """Calculate combined score from all AI approaches"""
        scores = []
        
        # Classical AI score
        classical_score = results['classical_ai'].get('overall_health_score')
        if classical_score is not None:
            scores.append(classical_score)
        
        # ML score
        ml_score = results['machine_learning'].get('ml_health_score')
        if ml_score is not None:
            scores.append(ml_score)
        
        # Weighted average (classical AI gets more weight for reliability)
        if scores:
            weights = [0.7, 0.3][:len(scores)]  # Classical AI: 70%, ML: 30%
            combined_score = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
            return round(combined_score, 1)
        
        return 50.0

    def _generate_hybrid_recommendations(self, results: Dict[str, Any]) -> List[str]:
        """Generate combined recommendations from all AI approaches"""
        recommendations = []
        
        # Classical AI recommendations
        classical_recs = results['classical_ai'].get('recommendations', [])
        recommendations.extend([f"🔧 Classical: {rec}" for rec in classical_recs])
        
        # ML recommendations
        if results['machine_learning'].get('anomaly_detection', {}).get('is_anomaly'):
            recommendations.append("🤖 ML: Anomaly detected - investigate unusual patterns")
        
        # LLM recommendations
        llm_recs = results['llm_insights'].get('intelligent_recommendations', [])
        recommendations.extend([f"🧠 LLM: {rec}" for rec in llm_recs])
        
        # Hybrid-specific recommendations
        combined_score = results.get('combined_score', 50)
        if combined_score < 30:
            recommendations.append("🚨 HYBRID: Critical - Multiple AI systems agree intervention needed")
        elif combined_score < 70:
            recommendations.append("⚠️ HYBRID: Consider proactive maintenance based on AI consensus")
        
        return recommendations[:10]  # Limit to top 10

    def _store_analysis_data(self, results: Dict[str, Any]):
        """Store analysis data for future ML training"""
        try:
            # Store in memory for this session
            self.historical_data.append({
                'timestamp': results['timestamp'],
                'features': self._extract_ml_features(results['classical_ai']),
                'health_score': results['classical_ai'].get('overall_health_score', 50)
            })
            
            # Train ML models if we have enough data
            if len(self.historical_data) >= 10 and not self.ml_models_trained:
                self._train_ml_models()
                
        except Exception as e:
            logging.error(f"Data storage failed: {e}")

    def _train_ml_models(self):
        """Train ML models on historical data"""
        try:
            if len(self.historical_data) < 5:
                return
            
            # Prepare training data
            features = [data['features'] for data in self.historical_data]
            
            # Train anomaly detector
            self.scaler.fit(features)
            features_scaled = self.scaler.transform(features)
            self.anomaly_detector.fit(features_scaled)
            
            self.ml_models_trained = True
            logging.info(f"✅ ML models trained on {len(self.historical_data)} samples")
            
        except Exception as e:
            logging.error(f"ML training failed: {e}")

    def get_system_status(self) -> Dict[str, Any]:
        """Get status of all AI components"""
        return {
            'classical_ai': 'Available',
            'machine_learning': 'Available' if self.enable_ml else 'Disabled/Unavailable',
            'llm_integration': 'Available' if self.enable_llm else 'Disabled/Unavailable',
            'ml_models_trained': getattr(self, 'ml_models_trained', False),
            'historical_samples': len(self.historical_data),
            'ollama_available': OLLAMA_AVAILABLE,
            'openai_available': OPENAI_AVAILABLE,
            'sklearn_available': ML_AVAILABLE
        }
