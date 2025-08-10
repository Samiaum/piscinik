# rag_system.py - Système RAG pour Piscinik (VERSION PROPRE)
import os
import numpy as np
import pandas as pd
import faiss
from typing import List, Tuple
from openai import AsyncOpenAI
import asyncio
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class PiscinikRAG:
    def __init__(self, data_dir: str = "rag_data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        # Fichiers
        self.csv_path = self.data_dir / "piscinik_knowledge.csv"
        self.embeddings_path = self.data_dir / "embeddings.npy"
        self.index_path = self.data_dir / "faiss_index.bin"
        
        # OpenAI client
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.embedding_model = "text-embedding-3-small"
        self.embedding_dim = 1536  # Dimension pour text-embedding-3-small
        
        # FAISS index et données
        self.index = None
        self.chunks = []
        self.initialized = False
        
    async def initialize(self):
        """Initialise le système RAG (embeddings une seule fois)"""
        if self.initialized:
            return
            
        try:
            if self._files_exist():
                await self._load_existing()
            else:
                # Pour éviter les timeouts, initialisation différée
                logger.warning("⚠️ Fichiers RAG non trouvés - création différée à la première utilisation")
                self.chunks = []
                self.initialized = True
                return
            
            self.initialized = True
            logger.info(f"✅ RAG initialisé avec {len(self.chunks)} chunks")
            
        except Exception as e:
            logger.error(f"❌ Erreur initialisation RAG: {e}")
            # Mode dégradé - continuer sans RAG
            self.chunks = []
            self.initialized = True
    
    def _files_exist(self) -> bool:
        """Vérifie si les fichiers d'index existent déjà"""
        return (self.csv_path.exists() and 
                self.embeddings_path.exists() and 
                self.index_path.exists())
    
    async def _load_existing(self):
        """Charge l'index existant (rapide)"""
        logger.info("📂 Chargement de l'index RAG existant...")
        
        # Charger les chunks
        df = pd.read_csv(self.csv_path)
        self.chunks = df['content'].tolist()
        
        # Charger l'index FAISS
        self.index = faiss.read_index(str(self.index_path))
        
        logger.info(f"✅ Index chargé : {len(self.chunks)} chunks")
    
    async def _create_embeddings(self):
        """Crée les embeddings (une seule fois)"""
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV non trouvé : {self.csv_path}")
        
        logger.info("🚀 Création des embeddings (première fois)...")
        
        # Lire le CSV
        df = pd.read_csv(self.csv_path)
        self.chunks = df['content'].tolist()
        
        # Créer les embeddings par batch
        embeddings = []
        batch_size = 20  # Plus petit pour éviter les rate limits
        
        for i in range(0, len(self.chunks), batch_size):
            batch = self.chunks[i:i + batch_size]
            
            try:
                response = await self.client.embeddings.create(
                    model=self.embedding_model,
                    input=batch
                )
                
                batch_embeddings = [data.embedding for data in response.data]
                embeddings.extend(batch_embeddings)
                
                logger.info(f"📊 Embeddings créés : {len(embeddings)}/{len(self.chunks)}")
                
                # Pause pour respecter les rate limits
                if i + batch_size < len(self.chunks):
                    await asyncio.sleep(0.2)
                    
            except Exception as e:
                logger.error(f"Erreur création embeddings batch {i}: {e}")
                raise
        
        # Créer l'index FAISS
        embeddings_array = np.array(embeddings, dtype=np.float32)
        
        # Normaliser pour cosine similarity
        faiss.normalize_L2(embeddings_array)
        
        # Créer l'index
        self.index = faiss.IndexFlatIP(self.embedding_dim)
        self.index.add(embeddings_array)
        
        # Sauvegarder
        np.save(self.embeddings_path, embeddings_array)
        faiss.write_index(self.index, str(self.index_path))
        
        logger.info("✅ Embeddings créés et sauvegardés")
    
    async def search(self, query: str, top_k: int = 3) -> List[Tuple[str, float]]:
        """Recherche les chunks les plus pertinents"""
        if not self.initialized:
            await self.initialize()
        
        # Si pas de chunks, créer les embeddings maintenant
        if not self.chunks and self.csv_path.exists():
            logger.info("🚀 Création différée des embeddings...")
            await self._create_embeddings()
        
        if not self.chunks:
            logger.warning("⚠️ Aucun chunk disponible")
            return []
        
        try:
            logger.info(f"🔍 Recherche RAG pour: '{query}'")
            
            # Créer l'embedding de la query
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=[query]
            )
            
            query_embedding = np.array([response.data[0].embedding], dtype=np.float32)
            faiss.normalize_L2(query_embedding)
            
            # Rechercher
            scores, indices = self.index.search(query_embedding, top_k)
            
            # Retourner les résultats
            results = []
            for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
                if 0 <= idx < len(self.chunks):
                    chunk = self.chunks[idx]
                    results.append((chunk, float(score)))
                    logger.info(f"📄 Résultat {i+1} (score: {score:.3f}): {chunk[:100]}...")
            
            logger.info(f"✅ {len(results)} chunks trouvés pour la recherche")
            return results
            
        except Exception as e:
            logger.error(f"❌ Erreur recherche RAG: {e}")
            return []
    
    async def get_answer(self, query: str) -> str:
        """Génère une réponse basée sur la recherche RAG"""
        try:
            logger.info(f"🤖 Génération réponse pour: '{query}'")
            
            # Rechercher les chunks pertinents
            relevant_chunks = await self.search(query, top_k=3)
            
            if not relevant_chunks:
                logger.warning("⚠️ Aucun chunk trouvé")
                return "Je n'ai pas trouvé d'information spécifique sur ce sujet dans ma base de connaissances."
            
            # Construire le contexte
            context_parts = []
            for chunk, score in relevant_chunks:
                if score > 0.5:  # Seuil baissé de 0.7 à 0.5 pour plus de résultats
                    context_parts.append(chunk)
                    logger.info(f"✅ Chunk retenu (score: {score:.3f})")
                else:
                    logger.info(f"❌ Chunk rejeté (score: {score:.3f}) - seuil trop bas")
            
            if not context_parts:
                logger.warning("⚠️ Aucun chunk au-dessus du seuil 0.5")
                # Prendre au moins le meilleur résultat
                context_parts = [relevant_chunks[0][0]]
                logger.info(f"🔄 Utilisation du meilleur résultat (score: {relevant_chunks[0][1]:.3f})")
            
            context = "\n\n".join(context_parts)
            logger.info(f"📝 Contexte construit avec {len(context_parts)} chunks")
            
            # Générer la réponse
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": """Tu es l'expert technique de Piscinik. Réponds aux questions en te basant 
                        STRICTEMENT sur le contexte fourni. Sois CONCIS, précis et pratique. 
                        Donne 2-3 conseils concrets maximum, sans détails inutiles. Évite les longs paragraphes.
                        Si l'information n'est pas dans le contexte, dis-le brièvement."""
                    },
                    {
                        "role": "user", 
                        "content": f"Contexte technique :\n{context}\n\nQuestion client : {query}\n\nRéponse courte et pratique :"
                    }
                ],
                temperature=0.3,  # Plus déterministe pour les réponses techniques
                max_tokens=150  # Réduit de 300 à 150 tokens pour des réponses plus courtes
            )
            
            final_answer = response.choices[0].message.content
            logger.info(f"🎯 Réponse générée: {final_answer}")
            
            return final_answer
            
        except Exception as e:
            logger.error(f"❌ Erreur génération réponse RAG: {e}")
            return "Je rencontre un problème technique pour accéder à ma base de connaissances. Pouvez-vous reformuler votre question ?"


# Instance globale pour réutilisation
_rag_instance = None

async def get_rag_system() -> PiscinikRAG:
    """Retourne l'instance RAG (singleton)"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = PiscinikRAG()
        await _rag_instance.initialize()
    return _rag_instance


# Test du système
async def test_rag():
    """Test du système RAG"""
    rag = await get_rag_system()
    
    questions = [
        "Ma piscine est verte, que faire ?",
        "Comment équilibrer le pH ?",
        "Quelle est la durée de filtration idéale ?",
        "Ma pompe ne s'amorce pas",
    ]
    
    for question in questions:
        print(f"\n❓ Question: {question}")
        answer = await rag.get_answer(question)
        print(f"🔧 Réponse: {answer}")

if __name__ == "__main__":
    asyncio.run(test_rag())