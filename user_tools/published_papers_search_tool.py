"""
Published Papers Research Tool for Agentic RAG System
Searches multiple academic databases for research papers with comprehensive error handling
"""

import asyncio
import aiohttp
import json
import re
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from urllib.parse import quote
import logging

# Handle optional dependencies gracefully
try:
    from Bio import Entrez
    HAS_BIOPYTHON = True
except ImportError:
    HAS_BIOPYTHON = False
    
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from .base_user_tool import BaseUserTool
    from .citation_mastery import format_source_block, extract_domain
except ImportError:
    from base_user_tool import BaseUserTool
    from citation_mastery import format_source_block, extract_domain

logger = logging.getLogger(__name__)

class PublishedPapersSearchTool(BaseUserTool):
    """
    A comprehensive academic paper search tool that queries multiple databases:
    - arXiv (preprints)
    - Semantic Scholar 
    - PubMed Central
    - Europe PMC
    - DOAJ (Directory of Open Access Journals)
    - bioRxiv/medRxiv
    - CORE (when API key available)
    
    Follows modular architecture principle: each method has 1-2 function calls max
    """
    
    def __init__(self):
        super().__init__()
        # Configure Entrez email for PubMed access if available
        if HAS_BIOPYTHON:
            Entrez.email = "agentic-rag@research.system"
        
        # Rate limiting configuration
        self.rate_limit_delay = 0.5  # seconds between API calls
        self.max_retries = 2
        self.timeout = 15  # seconds
    
    @property
    def name(self) -> str:
        return "published_papers_search"
    
    @property
    def description(self) -> str:
        return "Search academic databases for published research across ALL disciplines. STEM/biomedical: arXiv, PubMed, Europe PMC, bioRxiv. Cross-disciplinary & HUMANITIES: Semantic Scholar, OpenAlex, Crossref (incl. books), CORE, DOAJ, DOAB (open-access books), Internet Archive (digitized books & primary-source texts). Returns titles, authors, abstracts, dates, and URLs. Use for literature reviews and scholarly research in the sciences AND the humanities (history, law, arts). Pass the optional 'sources' list to restrict to domain-appropriate databases (e.g. history → openalex, crossref, doab, internet_archive; NOT arxiv/pubmed)."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research query or topic to search for (e.g., 'machine learning ethics', 'CRISPR gene editing', 'quantum computing')"
                },
                "year": {
                    "type": "integer", 
                    "description": "Optional publication year filter (e.g., 2024, 2023)"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results per source (default: 5, max: 20)",
                    "default": 5
                },
                "sources": {
                    "type": "array",
                    "description": "Optional specific sources to search. STEM/biomed: arxiv, pubmed, europe_pmc, biorxiv. Cross-disciplinary/humanities: semantic_scholar, openalex, crossref, core, doaj, doab, internet_archive. For non-STEM topics (history/law/arts) prefer the humanities set and OMIT arxiv/pubmed/biorxiv.",
                    "items": {"type": "string"}
                }
            },
            "required": ["query"]
        }
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """Main execution method following modular architecture"""
        try:
            # Step 1: Validate and prepare parameters (1 function call)
            validated_params = self._validate_and_prepare_params(kwargs)
            
            # Step 2: Execute parallel searches (1 function call)
            results = await self._search_all_sources(validated_params)
            
            # Step 3: Format and return results (1 function call)  
            return self._format_final_results(results)
            
        except Exception as e:
            logger.error(f"Published papers search error: {e}")
            return {
                "success": False,
                "error": f"Search failed: {str(e)}",
                "result": []
            }
    
    def _validate_and_prepare_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate parameters and set defaults (modular: 1-2 operations)"""
        query = kwargs.get("query", "").strip()
        if not query:
            raise ValueError("Query parameter is required")
        
        year = kwargs.get("year")
        if year and (year < 1900 or year > datetime.now().year + 1):
            raise ValueError(f"Year must be between 1900 and {datetime.now().year + 1}")
        
        max_results = min(kwargs.get("max_results", 5), 20)  # Cap at 20 for performance
        sources = kwargs.get("sources", [])
        
        return {
            "query": query,
            "year": year, 
            "max_results": max_results,
            "sources": sources
        }
    
    async def _search_all_sources(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute parallel searches across all sources (modular approach)"""
        # Step 1: Prepare search tasks
        search_tasks = self._prepare_search_tasks(params)
        
        # Step 2: Execute parallel searches with error handling
        raw_results = await self._execute_parallel_searches(search_tasks)
        
        # Step 3: Process and filter results
        return self._process_search_results(raw_results)
    
    def _prepare_search_tasks(self, params: Dict[str, Any]) -> List[tuple]:
        """Prepare search tasks for parallel execution"""
        query = params["query"]
        year = params["year"]
        max_results = params["max_results"]
        requested_sources = params["sources"]
        
        # Define all available search functions
        all_sources = [
            # STEM / biomedical
            ("arxiv", self._search_arxiv),
            ("pubmed", self._search_pubmed),
            ("europe_pmc", self._search_europe_pmc),
            ("biorxiv", self._search_biorxiv),
            # Cross-disciplinary / humanities (balance the STEM corpora)
            ("semantic_scholar", self._search_semantic_scholar),
            ("openalex", self._search_openalex),
            ("crossref", self._search_crossref),
            ("core", self._search_core),
            ("doaj", self._search_doaj),
            ("doab", self._search_doab),
            ("internet_archive", self._search_internet_archive),
        ]
        
        # Filter sources if specific ones requested
        if requested_sources:
            sources_to_search = [(name, func) for name, func in all_sources 
                               if name in requested_sources]
        else:
            sources_to_search = all_sources
        
        # Create tasks
        return [(name, func, query, year, max_results) for name, func in sources_to_search]
    
    async def _execute_parallel_searches(self, search_tasks: List[tuple]) -> List[tuple]:
        """Execute search tasks in parallel with rate limiting"""
        tasks = []
        for source_name, search_func, query, year, max_results in search_tasks:
            task = self._safe_search_with_delay(source_name, search_func, query, year, max_results)
            tasks.append(task)
        
        # Execute all searches in parallel
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _safe_search_with_delay(self, source_name: str, search_func, query: str, 
                                    year: Optional[int], max_results: int) -> tuple:
        """Execute single search with error handling and rate limiting"""
        try:
            # Add rate limiting delay
            await asyncio.sleep(self.rate_limit_delay)
            
            # Execute search
            results = await search_func(query, year, max_results)
            return (source_name, results, None)
            
        except Exception as e:
            logger.warning(f"Search failed for {source_name}: {e}")
            return (source_name, [], str(e))
    
    def _process_search_results(self, raw_results: List[tuple]) -> List[Dict[str, Any]]:
        """Process and combine search results from all sources"""
        all_papers = []
        successful_sources = []
        failed_sources = []
        
        for result in raw_results:
            if isinstance(result, Exception):
                failed_sources.append(f"Unknown source: {str(result)}")
                continue
                
            source_name, papers, error = result
            
            if error:
                failed_sources.append(f"{source_name}: {error}")
            else:
                successful_sources.append(source_name)
                all_papers.extend(papers)
        
        # Log search summary
        logger.info(f"Papers search: {len(successful_sources)} sources succeeded, "
                   f"{len(failed_sources)} failed, {len(all_papers)} total papers")
        
        return all_papers
    
    def _format_final_results(self, papers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Format final results using Citation Mastery for LLM accuracy"""
        if not papers:
            return {
                "success": True,
                "result": "No research papers found for the given query.",
                "error": None
            }
        
        # Format papers using Citation Mastery
        formatted_blocks = []
        for i, paper in enumerate(papers, 1):
            # Create comprehensive content for each paper
            content_parts = []
            
            # Add title and authors
            if paper.get("title"):
                content_parts.append(f"Title: {paper['title']}")
            
            if paper.get("authors"):
                authors = paper["authors"]
                if isinstance(authors, list):
                    authors = ", ".join(authors)
                content_parts.append(f"Authors: {authors}")
            
            # Add publication info
            if paper.get("published"):
                content_parts.append(f"Published: {paper['published']}")
            if paper.get("year"):
                content_parts.append(f"Year: {paper['year']}")
            if paper.get("source"):
                content_parts.append(f"Source Database: {paper['source']}")
            
            # Add abstract
            if paper.get("abstract"):
                content_parts.append(f"Abstract: {paper['abstract']}")
            
            # Add DOI and PDF links if available
            if paper.get("doi"):
                content_parts.append(f"DOI: {paper['doi']}")
            if paper.get("pdf_link"):
                content_parts.append(f"PDF: {paper['pdf_link']}")
            
            # Get URL for citation (required for Citation Mastery)
            source_url = paper.get("url")
            if not source_url:
                # Fallback to PDF link or DOI if no direct URL
                source_url = paper.get("pdf_link") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else None)
            
            if source_url:  # Only include papers with valid citation URLs
                title = paper.get("title", f"Research Paper {i}")
                content = "\n".join(content_parts)
                
                formatted_block = format_source_block(
                    source_url=source_url,
                    title=title,
                    content=content,
                    source_num=i
                )
                formatted_blocks.append(formatted_block)
        
        if not formatted_blocks:
            return {
                "success": True,
                "result": "No papers found with valid citation URLs.",
                "error": None
            }
        
        # Combine all formatted blocks
        combined_result = "\n".join(formatted_blocks)
        
        # Add summary header
        sources_searched = list(set(paper.get("source", "Unknown") for paper in papers))
        summary_header = f"""
🔬 ACADEMIC RESEARCH PAPERS SEARCH RESULTS
═══════════════════════════════════════════════════════
Total Papers Found: {len(formatted_blocks)}
Sources Searched: {', '.join(sources_searched)}
Search Timestamp: {datetime.now().strftime('%A, %B %d, %Y %I:%M:%S %p')}
═══════════════════════════════════════════════════════
"""
        
        final_result = summary_header + combined_result
        
        return {
            "success": True,
            "result": final_result,
            "error": None
        }
    
    # ==========================================
    # Individual Search Functions (Modular)
    # ==========================================
    
    async def _search_arxiv(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """Search arXiv preprint server"""
        try:
            url = self._build_arxiv_url(query, year, max_results)
            xml_data = await self._fetch_url_content(url)
            return self._parse_arxiv_xml(xml_data)
        except Exception as e:
            logger.error(f"arXiv search error: {e}")
            return []
    
    def _build_arxiv_url(self, query: str, year: Optional[int], max_results: int) -> str:
        """Build arXiv API URL"""
        base_url = "http://export.arxiv.org/api/query"
        search_query = f"all:{query}"
        
        if year:
            search_query += f" AND submittedDate:[{year}01010000 TO {year}12312359]"
        
        return f"{base_url}?search_query={quote(search_query)}&start=0&max_results={max_results}&sortBy=relevance&sortOrder=descending"
    
    def _parse_arxiv_xml(self, xml_data: str) -> List[Dict[str, Any]]:
        """Parse arXiv XML response"""
        try:
            from xml.etree import ElementTree
            root = ElementTree.fromstring(xml_data)
            entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
            
            results = []
            for entry in entries:
                paper_data = self._extract_arxiv_paper_data(entry)
                if paper_data:
                    results.append(paper_data)
            
            return results
        except Exception as e:
            logger.error(f"arXiv XML parsing error: {e}")
            return []
    
    def _extract_arxiv_paper_data(self, entry) -> Optional[Dict[str, Any]]:
        """Extract paper data from arXiv XML entry"""
        try:
            title_elem = entry.find("{http://www.w3.org/2005/Atom}title")
            title = title_elem.text.strip() if title_elem is not None else "No title"
            
            authors = []
            for author in entry.findall(".//{http://www.w3.org/2005/Atom}author"):
                name_elem = author.find("{http://www.w3.org/2005/Atom}name")
                if name_elem is not None:
                    authors.append(name_elem.text)
            
            published_elem = entry.find("{http://www.w3.org/2005/Atom}published")
            published = published_elem.text if published_elem is not None else "Unknown"
            
            id_elem = entry.find("{http://www.w3.org/2005/Atom}id")
            arxiv_id = id_elem.text.split("/abs/")[-1] if id_elem is not None else None
            pdf_link = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None
            
            summary_elem = entry.find("{http://www.w3.org/2005/Atom}summary")
            abstract = summary_elem.text.strip() if summary_elem is not None else "No abstract"
            if len(abstract) > 200:
                abstract = abstract[:200] + "..."
            
            # Create URL for citation
            arxiv_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None
            
            return {
                "source": "arXiv",
                "title": title,
                "authors": authors,
                "published": published,
                "arxiv_id": arxiv_id,
                "url": arxiv_url,  # Added for Citation Mastery
                "pdf_link": pdf_link,
                "abstract": abstract
            }
        except Exception:
            return None
    
    async def _search_semantic_scholar(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """Search Semantic Scholar API"""
        try:
            url = self._build_semantic_scholar_url(query, year, max_results)
            data = await self._fetch_json_content(url)
            return self._parse_semantic_scholar_data(data)
        except Exception as e:
            logger.error(f"Semantic Scholar search error: {e}")
            return []
    
    def _build_semantic_scholar_url(self, query: str, year: Optional[int], max_results: int) -> str:
        """Build Semantic Scholar API URL"""
        base_url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": query,
            "limit": max_results,
            "fields": "paperId,title,authors,year,abstract,isOpenAccess,openAccessPdf,publicationDate"
        }
        if year:
            params["year"] = year
        
        param_str = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
        return f"{base_url}?{param_str}"
    
    def _parse_semantic_scholar_data(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Semantic Scholar response data"""
        results = []
        for paper in data.get("data", []):
            pdf_link = None
            if paper.get("isOpenAccess") and paper.get("openAccessPdf"):
                pdf_link = paper["openAccessPdf"].get("url")
            
            authors = [author.get("name", "") for author in paper.get("authors", [])]
            abstract = paper.get("abstract", "")
            if abstract and len(abstract) > 200:
                abstract = abstract[:200] + "..."
            
            # Create URL for citation
            paper_id = paper.get("paperId")
            semantic_url = f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else None
            
            results.append({
                "source": "Semantic Scholar",
                "title": paper.get("title", "No title"),
                "authors": authors,
                "year": paper.get("year"),
                "published": paper.get("publicationDate", "Unknown"),
                "url": semantic_url,  # Added for Citation Mastery
                "abstract": abstract or "No abstract",
                "pdf_link": pdf_link,
                "paper_id": paper_id
            })
        
        return results
    
    async def _search_pubmed(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """Search PubMed Central (requires BioPython)"""
        if not HAS_BIOPYTHON:
            logger.warning("BioPython not available, skipping PubMed search")
            return []
        
        try:
            search_term = query
            if year:
                search_term += f" AND {year}[pdat]"
            
            # Execute search
            handle = Entrez.esearch(db="pmc", term=search_term, retmax=max_results)
            record = Entrez.read(handle)
            handle.close()
            
            if record["IdList"]:
                return await self._fetch_pmc_details(record["IdList"])
            return []
        except Exception as e:
            logger.error(f"PubMed search error: {e}")
            return []
    
    async def _fetch_pmc_details(self, pmc_ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch details for PMC articles"""
        results = []
        for pmc_id in pmc_ids:
            try:
                paper_data = await self._fetch_single_pmc_details(pmc_id)
                if paper_data:
                    results.append(paper_data)
            except Exception as e:
                logger.error(f"Error fetching PMC{pmc_id}: {e}")
        
        return results
    
    async def _fetch_single_pmc_details(self, pmc_id: str) -> Optional[Dict[str, Any]]:
        """Fetch details for a single PMC article"""
        try:
            handle = Entrez.efetch(db="pmc", id=pmc_id, rettype="xml", retmode="xml")
            record = Entrez.read(handle)
            handle.close()
            
            article = record[0] if record else None
            if not article:
                return None
            
            title = "No title"
            if "MedlineCitation" in article and "Article" in article["MedlineCitation"]:
                title = article["MedlineCitation"]["Article"].get("ArticleTitle", "No title")
            
            return {
                "source": "PubMed Central",
                "title": str(title),
                "pmc_id": f"PMC{pmc_id}",
                "url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/",
                "pdf_link": f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/pdf/"
            }
        except Exception:
            return None
    
    async def _search_europe_pmc(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """Search Europe PMC for open access papers"""
        try:
            url = self._build_europe_pmc_url(query, year, max_results)
            data = await self._fetch_json_content(url)
            return self._parse_europe_pmc_data(data)
        except Exception as e:
            logger.error(f"Europe PMC search error: {e}")
            return []
    
    def _build_europe_pmc_url(self, query: str, year: Optional[int], max_results: int) -> str:
        """Build Europe PMC API URL"""
        base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        search_query = query
        if year:
            search_query += f" AND YEAR:{year}"
        
        params = {
            "query": search_query,
            "resultType": "core",
            "pageSize": max_results,
            "format": "json"
        }
        
        param_str = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
        return f"{base_url}?{param_str}"
    
    def _parse_europe_pmc_data(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Europe PMC response data"""
        results = []
        articles = data.get("resultList", {}).get("result", [])
        
        for article in articles:
            pdf_link = None
            if article.get("isOpenAccess") == "Y" and article.get("pmcid"):
                pdf_link = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={article['pmcid']}&blobtype=pdf"
            
            abstract = article.get("abstractText", "")
            if abstract and len(abstract) > 200:
                abstract = abstract[:200] + "..."
            
            authors = article.get("authorString", "").split(", ") if article.get("authorString") else []
            
            # Create URL for citation. EuropePMC article URLs are /article/{SOURCE}/{ID} and the SOURCE↔ID
            # MUST match (MED→PubMed id, PMC→PMCID, PPR→preprint id, …). The API returns the correct pair as
            # `source`+`id`; the old MED/{pmcid} form builds a MISMATCHED pair that renders a client-side
            # "Page not found" (a SOFT-404: HTTP 200, so no link checker catches it). Use the record's own
            # source+id (correct for every source, no hardcoded namespace); fall back to the primary DOI.
            pmcid = article.get("pmcid")
            doi = article.get("doi")
            src = article.get("source")
            aid = article.get("id")
            europe_url = None
            if src and aid:
                europe_url = f"https://europepmc.org/article/{src}/{aid}"
            elif doi:
                europe_url = f"https://doi.org/{doi}"
            
            results.append({
                "source": "Europe PMC",
                "title": article.get("title", "No title"),
                "authors": authors,
                "published": article.get("firstPublicationDate"),
                "url": europe_url,  # Added for Citation Mastery
                "abstract": abstract or "No abstract",
                "pdf_link": pdf_link,
                "pmcid": pmcid,
                "doi": doi
            })
        
        return results
    
    async def _search_doaj(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """Search Directory of Open Access Journals"""
        try:
            url = self._build_doaj_url(query, year, max_results)
            data = await self._fetch_json_content(url)
            return self._parse_doaj_data(data)
        except Exception as e:
            logger.error(f"DOAJ search error: {e}")
            return []
    
    def _build_doaj_url(self, query: str, year: Optional[int], max_results: int) -> str:
        """Build DOAJ API URL"""
        base_url = "https://doaj.org/api/search/articles"
        search_query = query
        if year:
            search_query += f" AND year:{year}"
        
        params = {
            "q": search_query,
            "pageSize": max_results,
            "page": 1
        }
        
        param_str = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
        return f"{base_url}?{param_str}"
    
    def _parse_doaj_data(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse DOAJ response data"""
        results = []
        articles = data.get("results", [])
        
        for article in articles:
            bibjson = article.get("bibjson", {})
            
            authors = []
            for author in bibjson.get("author", []):
                name = author.get("name", "")
                if name:
                    authors.append(name)
            
            pdf_link = None
            for link in bibjson.get("link", []):
                if link.get("type") == "fulltext":
                    pdf_link = link.get("url")
                    break
            
            abstract = bibjson.get("abstract", "")
            if abstract and len(abstract) > 200:
                abstract = abstract[:200] + "..."
            
            doi = None
            identifiers = bibjson.get("identifier", [])
            if identifiers:
                doi = identifiers[0].get("id")
            
            results.append({
                "source": "DOAJ",
                "title": bibjson.get("title", "No title"),
                "authors": authors,
                "year": bibjson.get("year"),
                "abstract": abstract or "No abstract",
                "pdf_link": pdf_link,
                "doi": doi
            })
        
        return results
    
    async def _search_biorxiv(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """Search bioRxiv and medRxiv preprint servers"""
        try:
            url = self._build_biorxiv_url(year, max_results)
            data = await self._fetch_json_content(url)
            return self._filter_biorxiv_results(data, query, max_results)
        except Exception as e:
            logger.error(f"bioRxiv search error: {e}")
            return []
    
    def _build_biorxiv_url(self, year: Optional[int], max_results: int) -> str:
        """Build bioRxiv API URL"""
        if year:
            start_date = f"{year}-01-01"
            end_date = f"{year}-12-31"
        else:
            current_year = datetime.now().year
            start_date = f"{current_year-1}-01-01"
            end_date = f"{current_year}-12-31"
        
        return f"https://api.biorxiv.org/details/biorxiv/{start_date}/{end_date}/0/{max_results}"
    
    def _filter_biorxiv_results(self, data: Dict[str, Any], query: str, max_results: int) -> List[Dict[str, Any]]:
        """Filter bioRxiv results by query relevance"""
        results = []
        query_lower = query.lower()
        
        for article in data.get("collection", []):
            title = article.get("title", "").lower()
            abstract = article.get("abstract", "").lower()
            
            if query_lower in title or query_lower in abstract:
                abstract_text = article.get("abstract", "")
                if abstract_text and len(abstract_text) > 200:
                    abstract_text = abstract_text[:200] + "..."
                
                # Create URL for citation
                doi = article.get("doi")
                biorxiv_url = f"https://www.biorxiv.org/content/{doi}" if doi else None
                
                results.append({
                    "source": "bioRxiv/medRxiv",
                    "title": article.get("title", "No title"),
                    "authors": article.get("authors", "Unknown authors"),
                    "published": article.get("date"),
                    "url": biorxiv_url,  # Added for Citation Mastery
                    "doi": doi,
                    "pdf_link": f"https://www.biorxiv.org/content/{doi}.full.pdf" if doi else None,
                    "abstract": abstract_text or "No abstract"
                })
        
        return results[:max_results]
    
    async def _search_core(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """Search CORE (requires API key for production use)"""
        try:
            url = self._build_core_url(query, year, max_results)
            data = await self._fetch_json_content(url)
            return self._parse_core_data(data)
        except Exception as e:
            logger.warning(f"CORE search error (likely needs API key): {e}")
            return []
    
    def _build_core_url(self, query: str, year: Optional[int], max_results: int) -> str:
        """Build CORE API URL"""
        base_url = "https://api.core.ac.uk/v3/search/works"
        search_query = query
        if year:
            search_query += f" AND yearPublished:{year}"
        
        params = {
            "q": search_query,
            "limit": max_results
        }
        
        param_str = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
        return f"{base_url}?{param_str}"
    
    def _parse_core_data(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse CORE response data"""
        results = []
        items = data.get("results", [])
        
        for item in items:
            authors = [author.get("name", "") for author in item.get("authors", [])]
            abstract = item.get("abstract", "")
            if abstract and len(abstract) > 200:
                abstract = abstract[:200] + "..."
            
            results.append({
                "source": "CORE",
                "title": item.get("title", "No title"),
                "authors": authors,
                "year": item.get("yearPublished"),
                "abstract": abstract or "No abstract",
                "pdf_link": item.get("downloadUrl"),
                "doi": item.get("doi")
            })
        
        return results
    
    # ==========================================
    # Utility Methods
    # ==========================================
    
    async def _fetch_url_content(self, url: str) -> str:
        """Fetch URL content as text"""
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text()
    
    # ===== Humanities / cross-disciplinary corpora (balance the STEM-heavy sources so history/humanities
    # queries have real coverage). See docs/RAICA_DR_SOURCE_RELEVANCE.md. =====

    @staticmethod
    def _openalex_abstract(inv: Optional[Dict[str, Any]]) -> str:
        """Reconstruct an abstract from OpenAlex's inverted index {word: [positions]}."""
        if not inv:
            return ""
        pos: Dict[int, str] = {}
        for w, ps in inv.items():
            for p in ps:
                pos[p] = w
        return " ".join(pos[i] for i in sorted(pos))[:200]

    async def _search_openalex(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """OpenAlex — 250M+ works across ALL disciplines (incl. humanities); robust free API."""
        try:
            url = f"https://api.openalex.org/works?search={quote(query)}&per-page={max_results}"
            if year:
                url += f"&filter=publication_year:{year}"
            data = await self._fetch_json_content(url)
            out = []
            for w in (data.get("results", []) or [])[:max_results]:
                doi = w.get("doi")
                loc = w.get("primary_location") or {}
                base_title = w.get("title") or w.get("display_name") or "No title"
                # Carry the parent venue/book (container) so a generic chapter title keeps its topical context.
                src = (loc.get("source") or {}) if isinstance(loc, dict) else {}
                container = (src.get("display_name") or "") if isinstance(src, dict) else ""
                title = (f"{base_title} — in: {container}"
                         if container and container.strip().lower() != base_title.strip().lower()
                         else base_title)
                authors = [a.get("author", {}).get("display_name") for a in (w.get("authorships") or [])]
                out.append({
                    "source": "OpenAlex",
                    "title": title,
                    "authors": [a for a in authors if a],
                    "year": w.get("publication_year"),
                    "url": doi or (loc.get("landing_page_url") if isinstance(loc, dict) else None) or w.get("id"),
                    "doi": doi,
                    "pdf_link": (loc.get("pdf_url") if isinstance(loc, dict) else None),
                    "abstract": self._openalex_abstract(w.get("abstract_inverted_index")) or "No abstract",
                })
            return out
        except Exception as e:
            logger.error(f"OpenAlex search error: {e}")
            return []

    async def _search_crossref(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """Crossref — DOI metadata for scholarly works incl. BOOKS and humanities journals."""
        try:
            url = f"https://api.crossref.org/works?query={quote(query)}&rows={max_results}"
            if year:
                url += f"&filter=from-pub-date:{year}-01-01,until-pub-date:{year}-12-31"
            data = await self._fetch_json_content(url)
            out = []
            for it in (data.get("message", {}).get("items", []) or [])[:max_results]:
                titles = it.get("title") or []
                base_title = titles[0] if titles else "No title"
                # Carry the PARENT book/journal (container-title). A book chapter often has a GENERIC title
                # ("Consideration of Counterarguments", "Introduction") that is topically ambiguous alone — the
                # container reveals the real subject (e.g. that chapter is from "The Ethical Case against Animal
                # Experiments", NOT Byzantine history). Without it, generic chapter titles get mis-cited.
                container = (it.get("container-title") or [""])
                container = container[0] if container else ""
                title = (f"{base_title} — in: {container}"
                         if container and container.strip().lower() != base_title.strip().lower()
                         else base_title)
                authors = [f"{a.get('given', '')} {a.get('family', '')}".strip()
                           for a in (it.get("author") or [])]
                dp = (it.get("issued") or {}).get("date-parts") or [[None]]
                yr = dp[0][0] if (dp and dp[0]) else None
                out.append({
                    "source": "Crossref",
                    "title": title,
                    "authors": [a for a in authors if a],
                    "year": yr,
                    "url": it.get("URL") or (f"https://doi.org/{it.get('DOI')}" if it.get("DOI") else None),
                    "doi": it.get("DOI"),
                    "pdf_link": None,
                    "abstract": re.sub(r"<[^>]+>", "", it.get("abstract", "") or "")[:200] or "No abstract",
                })
            return out
        except Exception as e:
            logger.error(f"Crossref search error: {e}")
            return []

    async def _search_internet_archive(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """Internet Archive — digitized BOOKS / primary-source TEXTS (mediatype:texts only)."""
        try:
            q = f"{query} AND mediatype:texts"
            if year:
                q += f" AND year:{year}"
            url = ("https://archive.org/advancedsearch.php?q=" + quote(q) +
                   "&fl[]=identifier&fl[]=title&fl[]=creator&fl[]=year&fl[]=description"
                   f"&rows={max_results}&output=json")
            data = await self._fetch_json_content(url)
            out = []
            for d in (data.get("response", {}).get("docs", []) or [])[:max_results]:
                ident = d.get("identifier")
                if not ident:
                    continue
                title = d.get("title")
                title = (title[0] if isinstance(title, list) and title else title)
                creator = d.get("creator")
                authors = creator if isinstance(creator, list) else ([creator] if creator else [])
                desc = d.get("description")
                desc = (desc[0] if isinstance(desc, list) and desc else desc)
                out.append({
                    "source": "Internet Archive",
                    "title": title or "No title",
                    "authors": authors,
                    "year": d.get("year"),
                    "url": f"https://archive.org/details/{ident}",
                    "doi": None,
                    "pdf_link": None,
                    "abstract": (str(desc)[:200] if desc else "No abstract"),
                })
            return out
        except Exception as e:
            logger.error(f"Internet Archive search error: {e}")
            return []

    async def _search_doab(self, query: str, year: Optional[int], max_results: int) -> List[Dict[str, Any]]:
        """DOAB — Directory of Open Access BOOKS (humanities-heavy). Legacy DSpace REST endpoint."""
        try:
            url = ("https://directory.doabooks.org/rest/search?query=" + quote(query) +
                   f"&limit={max_results}&expand=metadata")
            data = await self._fetch_json_content(url)
            items = data if isinstance(data, list) else []
            out = []
            for it in items[:max_results]:
                md = {m.get("key"): m.get("value") for m in (it.get("metadata") or [])}
                handle = it.get("handle")
                yr = md.get("dc.date.issued")
                yr = (yr[:4] if isinstance(yr, str) and len(yr) >= 4 else yr)
                out.append({
                    "source": "DOAB",
                    "title": it.get("name") or md.get("dc.title") or "No title",
                    "authors": [md["dc.contributor.author"]] if md.get("dc.contributor.author") else [],
                    "year": yr,
                    "url": (f"https://directory.doabooks.org/handle/{handle}" if handle
                            else md.get("dc.identifier.uri")),
                    "doi": None,
                    "pdf_link": None,
                    "abstract": (str(md.get("dc.description.abstract", ""))[:200] or "No abstract"),
                })
            return out
        except Exception as e:
            logger.error(f"DOAB search error: {e}")
            return []

    async def _fetch_json_content(self, url: str):
        """Fetch URL content as JSON. Sends a UA (OpenAlex/Crossref polite pools, DOAB legacy REST) and
        parses regardless of the server's content-type header (archive.org/DOAB return json as text)."""
        headers = {"Accept": "application/json",
                   "User-Agent": "RAICA-research/1.0 (academic literature search)"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.json(content_type=None)