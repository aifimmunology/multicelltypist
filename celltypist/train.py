import numpy as np
import pandas as pd
import scanpy as sc
from scanpy import AnnData
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import SGDClassifier
from typing import Optional, Union
from .models import Model
from . import logger
from scipy.sparse import spmatrix

def _load_file_as_list(_file):
    """
    For internal use. Load file if it is a string.
    """
    if isinstance(_file, str):
        try:
            return pd.read_csv(_file, header=None)[0].values
        except Exception as e:
            raise Exception(f"🛑 {e}")
    else:
        return np.array(_file)

def _prepare_data(X, labels, genes, transpose):
    """
    For internal use. Prepare data for celltypist training.
    """
    if (X is None) or (labels is None):
        raise Exception("🛑 Missing training data and/or training labels. Please provide both arguments")
    if isinstance(X, AnnData) or (isinstance(X, str) and X.endswith('.h5ad')):
        adata = sc.read(X) if isinstance(X, str) else X
        if adata.X.min() < 0:
            logger.info("👀 Detected scaled expression in the input data, will try the .raw attribute")
            try:
                indata = adata.raw.X.copy()
                genes = adata.raw.var_names.copy()
            except Exception as e:
                raise Exception(f"🛑 Fail to use the .raw attribute in the input object. {e}")
        else:
            indata = adata.X.copy()
            genes = adata.var_names.copy()
        if np.abs(np.expm1(indata[0]).sum()-10000) > 1:
            raise ValueError("🛑 Invalid expression matrix, expect log1p normalized expression to 10000 counts per cell")
        if isinstance(labels, str):
            if labels in adata.obs:
                labels = adata.obs[labels]
            else:
                labels = _load_file_as_list(labels)
        if len(labels) != indata.shape[0]:
            raise ValueError(f"🛑 Length of training labels ({len(labels)}) does not match the number of input cells ({indata.shape[0]})")
    elif isinstance(X, str) and X.endswith(('.csv', '.txt', '.tsv', '.tab', '.mtx', '.mtx.gz')):
        adata = sc.read(X)
        if transpose:
            adata = adata.transpose()
        if X.endswith(('.mtx', '.mtx.gz')):
            if genes is None:
                raise Exception("🛑 Missing `genes`. Please provide this argument together with the input mtx file")
            genes = _load_file_as_list(genes)
            if len(genes) != adata.n_vars:
                raise ValueError(f"🛑 The number of genes does not match the number of genes in {X}")
            adata.var_names = genes
        adata.var_names_make_unique()
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
        indata = adata.X.copy()
        genes = adata.var_names.copy()
        labels = _load_file_as_list(labels)
        if len(labels) != indata.shape[0]:
            raise ValueError(f"🛑 Length of training labels ({len(labels)}) does not match the number of input cells ({indata.shape[0]})")
    elif isinstance(X, str):
        raise ValueError("🛑 Invalid input. Supported types: .csv, .txt, .tsv, .tab, .mtx, .mtx.gz and .h5ad")
    else:
        logger.info("👀 The input training data is processed as an array-like object")
        indata = X.copy()
        if transpose:
            indata = indata.transpose()
        if isinstance(indata, pd.DataFrame):
            genes = indata.columns
            indata = indata.values
        else:
            if isinstance(indata, spmatrix):
                indata = indata.toarray()
            elif isinstance(indata, np.matrix):
                indata = np.array(indata)
            elif isinstance(indata, np.ndarray):
                indata = indata
            else:
                raise ValueError(f"🛑 Please provide a valid array-like object as input")
            if genes is None:
                raise Exception("🛑 Missing `genes`. Please provide this argument together with the input training data")
            genes = _load_file_as_list(genes)
            if len(genes) != indata.shape[1]:
                raise ValueError(f"🛑 The number of genes provided does not match the number of genes in the training data")
        if np.abs(np.expm1(indata[0]).sum()-10000) > 1:
            raise ValueError("🛑 Invalid expression matrix, expect log1p normalized expression to 10000 counts per cell")
        labels = _load_file_as_list(labels)
        if len(labels) != indata.shape[0]:
            raise ValueError(f"🛑 Length of training labels ({len(labels)}) does not match the number of input cells ({indata.shape[0]})")
    return indata, labels, genes

def _SGDClassifier(indata, labels,
                   alpha, max_iter, n_jobs,
                   mini_batch, batch_number, batch_size, epochs, **kwargs):
    """
    For internal use. Get the SGDClassifier.
    """
    classifier = SGDClassifier(loss = 'log', alpha = alpha, max_iter = max_iter, n_jobs = n_jobs, **kwargs)
    if not mini_batch:
        logger.info(f"🏋️ Training data using SGD logistic regression")
        classifier.fit(indata, labels)
    else:
        logger.info(f"🏋️ Training data using mini-batch SGD logistic regression")
        no_cells = len(labels)
        if no_cells <= batch_size:
            raise Exception(f"🛑 Number of cells is fewer than the batch size ({batch_size}). Decrease `batch_size`, or use SGD directly (mini_batch = False)")
        for epoch in range(1, (epochs+1)):
            logger.info(f"⏳ Epochs: [{epoch}/{epochs}]")
            indata, labels = shuffle(indata, labels)
            mini_batches = [indata[k:k+batch_size] for k in range(0, no_cells, batch_size)]
            mini_labels = [labels[k:k+batch_size] for k in range(0, no_cells, batch_size)]
            if batch_number < len(mini_batches):
                s = np.random.choice(range(0, len(mini_batches)), batch_number)
                mini_batches = [mini_batches[i] for i in s]
                mini_labels = [mini_labels[i] for i in s]
            for mini_batch, mini_label in zip(mini_batches, mini_labels):
                classifier.partial_fit(mini_batch, mini_label, classes = np.unique(labels))
    return classifier

def train(X = None,
          labels: Optional[Union[str, list, tuple, np.ndarray, pd.Series]] = None,
          genes: Optional[Union[str, list, tuple, np.ndarray, pd.Series]] = None,
          transpose_input: bool = False,
          #SGD param
          alpha: float = 0.0001, max_iter: int = 1000, n_jobs = None,
          #mini-batch
          mini_batch: bool = False, batch_number: int = 100, batch_size: int = 1000, epochs: int = 10,
          #feature selection
          feature_selection: bool = False, top_genes: int = 500,
          #description
          date: str = '', details: str = '', url: str = '',
          #other SGD param
          **kwargs
         ) -> Model:
    """
    coming soon...
    """
    logger.info("🍳 Preparing data before training")
    indata, labels, genes = _prepare_data(X, labels, genes, transpose_input)
    flag = indata.sum(axis = 0) == 0
    if flag.sum() > 0:
        logger.info(f"✂️ {flag.sum()} non-expressed genes are filtered out")
        indata = indata[:, ~flag]
        genes = genes[~flag]
    #scaler
    logger.info(f"⚖️ Scaling input data")
    scaler = StandardScaler()
    indata = scaler.fit_transform(indata)
    indata = np.clip(indata, a_min = None, a_max = 10)
    #classifier
    classifier = _SGDClassifier(indata = indata, labels = labels,
                                alpha = alpha, max_iter = max_iter, n_jobs = n_jobs,
                                mini_batch = mini_batch, batch_number = batch_number, batch_size = batch_size, epochs = epochs, **kwargs)
    #feature selection
    if feature_selection:
        logger.info(f"🔎 Selecting features")
        gene_index = np.argpartition(np.abs(classifier.coef_), -top_genes)[:, -top_genes:]
        gene_index = np.unique(gene_index)
        genes = genes[gene_index]
        indata = indata[:, gene_index]
        logger.info(f"🏋️ Starting the second round of training")
        classifier = _SGDClassifier(indata = indata, labels = labels,
                                    alpha = alpha, max_iter = max_iter, n_jobs = n_jobs,
                                    mini_batch = mini_batch, batch_number = batch_number, batch_size = batch_size, epochs = epochs, **kwargs)
        scaler.mean_ = scaler.mean_[gene_index]
        scaler.var_ = scaler.var_[gene_index]
        scaler.scale_ = scaler.scale_[gene_index]
        a.scaler.n_features_in_ = len(gene_index)
    #Model
    classifier.features = np.array(genes)
    description = {'date': date, 'details': details, 'url': url}
    logger.info(f"✅ Model training done!")
    return Model(classifier, scaler, description)