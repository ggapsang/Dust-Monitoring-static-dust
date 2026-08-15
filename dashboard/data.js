// padtools.dashboard 가 만든 파일이다. 직접 고치지 않는다.
window.PADDATA = {
 "source": "assets/samples",
 "tone": "white",
 "config": {
  "spec": "legacy",
  "pad_size_px": 1120,
  "pad_size_mm": null,
  "detect": {
   "blur_ksize": 5,
   "min_pad_area_ratio": 0.005,
   "max_pad_area_ratio": 0.98,
   "approx_epsilon_ratio": 0.02,
   "require_ring": true,
   "min_solidity": 0.85,
   "max_aspect_ratio": 3.0,
   "edge_trim_ratio": 0.15,
   "threshold_scales": [
    1.0,
    1.15,
    1.3,
    1.45
   ]
  },
  "orient": {
   "min_margin": null
  },
  "quality": {
   "max_edge_rise_ratio": null,
   "min_tenengrad": null,
   "max_saturated_bright_ratio": null,
   "max_saturated_dark_ratio": null,
   "min_pad_size_px": null,
   "max_pad_size_diff_ratio": null,
   "saturation_bright_level": null,
   "saturation_dark_level": null
  },
  "normalize": {
   "gradient_correction": true,
   "ring_samples": 600
  },
  "dust": {
   "local_window": 0.08,
   "depth_threshold": 0.05,
   "min_blob_px": 4,
   "clean_percentile": 90.0,
   "max_blobs": 50
  },
  "score": {
   "uniform_reference": null,
   "localized_reference": null
  },
  "visualize": {
   "heat_max": 0.5
  },
  "lines": {
   "enabled": true
  },
  "target_id": {
   "enabled": true,
   "digits": null,
   "font_dir": "C:\\fems\\assets\\fonts"
  },
  "service": {
   "host": "0.0.0.0",
   "port": 8911
  }
 },
 "points": [
  {
   "id": "001",
   "set": "001_260815_1",
   "tone": "white",
   "baseline_source": "001_260815_1_baseline.jpg",
   "readings": [
    {
     "seq": 1,
     "source": "001_260815_1_test_01.jpg",
     "success": true,
     "elapsed_ms": 1749.4,
     "scores": {
      "uniform": 0.0947,
      "localized": 0.0065,
      "combined": 0.1006
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00397,
      "saturated_ratio": 0.0,
      "pad_size_px": 319.6,
      "pad_size_diff_ratio": 0.0502
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/001_01_rectified.jpg",
      "distribution": "img/001_01_distribution.jpg"
     }
    },
    {
     "seq": 2,
     "source": "001_260815_1_test_02.jpg",
     "success": true,
     "elapsed_ms": 1528.1,
     "scores": {
      "uniform": 0.1626,
      "localized": 0.0629,
      "combined": 0.2153
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00438,
      "saturated_ratio": 0.0,
      "pad_size_px": 384.8,
      "pad_size_diff_ratio": 0.2111
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/001_02_rectified.jpg",
      "distribution": "img/001_02_distribution.jpg"
     }
    },
    {
     "seq": 3,
     "source": "001_260815_1_test_03.jpg",
     "success": true,
     "elapsed_ms": 1374.9,
     "scores": {
      "uniform": 0.2165,
      "localized": 0.1242,
      "combined": 0.3138
     },
     "target_id": "1878",
     "quality": {
      "sharpness": 0.00389,
      "saturated_ratio": 0.0,
      "pad_size_px": 421.5,
      "pad_size_diff_ratio": 0.2798
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/001_03_rectified.jpg",
      "distribution": "img/001_03_distribution.jpg"
     }
    },
    {
     "seq": 4,
     "source": "001_260815_1_test_04.jpg",
     "success": true,
     "elapsed_ms": 1366.9,
     "scores": {
      "uniform": 0.2412,
      "localized": 0.1521,
      "combined": 0.3566
     },
     "target_id": "1067",
     "quality": {
      "sharpness": 0.0046,
      "saturated_ratio": 0.0,
      "pad_size_px": 412.0,
      "pad_size_diff_ratio": 0.2633
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/001_04_rectified.jpg",
      "distribution": "img/001_04_distribution.jpg"
     }
    }
   ],
   "baseline_image": "img/001_baseline.jpg"
  },
  {
   "id": "002",
   "set": "002_260815_2",
   "tone": "white",
   "baseline_source": "002_260815_2_baseline.jpg",
   "readings": [
    {
     "seq": 1,
     "source": "002_260815_2_test_01.jpg",
     "success": true,
     "elapsed_ms": 2056.4,
     "scores": {
      "uniform": 0.1212,
      "localized": 0.0104,
      "combined": 0.1303
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00409,
      "saturated_ratio": 0.0,
      "pad_size_px": 359.7,
      "pad_size_diff_ratio": 0.2794
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/002_01_rectified.jpg",
      "distribution": "img/002_01_distribution.jpg"
     }
    },
    {
     "seq": 2,
     "source": "002_260815_2_test_02.jpg",
     "success": true,
     "elapsed_ms": 1994.8,
     "scores": {
      "uniform": 0.1258,
      "localized": 0.0425,
      "combined": 0.1629
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00401,
      "saturated_ratio": 0.0,
      "pad_size_px": 372.8,
      "pad_size_diff_ratio": 0.3046
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/002_02_rectified.jpg",
      "distribution": "img/002_02_distribution.jpg"
     }
    },
    {
     "seq": 3,
     "source": "002_260815_2_test_03.jpg",
     "success": true,
     "elapsed_ms": 2343.1,
     "scores": {
      "uniform": 0.158,
      "localized": 0.0877,
      "combined": 0.2318
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00372,
      "saturated_ratio": 0.0,
      "pad_size_px": 386.9,
      "pad_size_diff_ratio": 0.3299
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/002_03_rectified.jpg",
      "distribution": "img/002_03_distribution.jpg"
     }
    },
    {
     "seq": 4,
     "source": "002_260815_2_test_04.jpg",
     "success": true,
     "elapsed_ms": 1725.0,
     "scores": {
      "uniform": 0.2158,
      "localized": 0.1578,
      "combined": 0.3395
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00468,
      "saturated_ratio": 0.0,
      "pad_size_px": 391.2,
      "pad_size_diff_ratio": 0.3374
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/002_04_rectified.jpg",
      "distribution": "img/002_04_distribution.jpg"
     }
    },
    {
     "seq": 5,
     "source": "002_260815_2_test_05.jpg",
     "success": true,
     "elapsed_ms": 1985.6,
     "scores": {
      "uniform": 0.2187,
      "localized": 0.1811,
      "combined": 0.3602
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00316,
      "saturated_ratio": 0.00027,
      "pad_size_px": 469.7,
      "pad_size_diff_ratio": 0.4481
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/002_05_rectified.jpg",
      "distribution": "img/002_05_distribution.jpg"
     }
    }
   ],
   "baseline_image": "img/002_baseline.jpg"
  },
  {
   "id": "003",
   "set": "003_260815_3",
   "tone": "white",
   "baseline_source": "003_260815_3_baseline.jpg",
   "readings": [
    {
     "seq": 1,
     "source": "003_260815_3_test_01.jpg",
     "success": true,
     "elapsed_ms": 1471.4,
     "scores": {
      "uniform": 0.0079,
      "localized": 0.0004,
      "combined": 0.0083
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.004,
      "saturated_ratio": 0.0,
      "pad_size_px": 328.1,
      "pad_size_diff_ratio": 0.2058
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/003_01_rectified.jpg",
      "distribution": "img/003_01_distribution.jpg"
     }
    },
    {
     "seq": 2,
     "source": "003_260815_3_test_02.jpg",
     "success": true,
     "elapsed_ms": 1547.5,
     "scores": {
      "uniform": 0.0151,
      "localized": 0.0098,
      "combined": 0.0247
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00469,
      "saturated_ratio": 0.0,
      "pad_size_px": 265.8,
      "pad_size_diff_ratio": 0.0198
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/003_02_rectified.jpg",
      "distribution": "img/003_02_distribution.jpg"
     }
    },
    {
     "seq": 3,
     "source": "003_260815_3_test_03.jpg",
     "success": true,
     "elapsed_ms": 1576.7,
     "scores": {
      "uniform": 0.0317,
      "localized": 0.0256,
      "combined": 0.0565
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00448,
      "saturated_ratio": 0.0,
      "pad_size_px": 261.0,
      "pad_size_diff_ratio": 0.0019
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/003_03_rectified.jpg",
      "distribution": "img/003_03_distribution.jpg"
     }
    },
    {
     "seq": 4,
     "source": "003_260815_3_test_04.jpg",
     "success": true,
     "elapsed_ms": 1589.8,
     "scores": {
      "uniform": 0.0633,
      "localized": 0.07,
      "combined": 0.1289
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00524,
      "saturated_ratio": 0.0,
      "pad_size_px": 281.6,
      "pad_size_diff_ratio": 0.0749
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/003_04_rectified.jpg",
      "distribution": "img/003_04_distribution.jpg"
     }
    },
    {
     "seq": 5,
     "source": "003_260815_3_test_05.jpg",
     "success": true,
     "elapsed_ms": 1510.3,
     "scores": {
      "uniform": 0.0938,
      "localized": 0.114,
      "combined": 0.1972
     },
     "target_id": "1078",
     "quality": {
      "sharpness": 0.00429,
      "saturated_ratio": 0.0,
      "pad_size_px": 303.7,
      "pad_size_diff_ratio": 0.142
     },
     "excluded_px": {
      "print_element": 0,
      "saturated": 0
     },
     "images": {
      "rectified": "img/003_05_rectified.jpg",
      "distribution": "img/003_05_distribution.jpg"
     }
    }
   ],
   "baseline_image": "img/003_baseline.jpg"
  }
 ]
};
